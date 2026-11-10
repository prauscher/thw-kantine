"""Views der Strichliste.

Jeder View ist fest einem Zugang zugeordnet: öffentlich, Nextcloud-Login
(JWT, bucht immer auf das eigene Konto) oder Theken-Tablet (URL enthält die
PIN, bucht auf ein beliebiges Konto). Ausgabe, Überweisung und Storno gibt es
für beide, die Mixins legen fest, um welches Konto es geht.
"""
import secrets

import segno
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import FormView, ListView, TemplateView, View

from kantine.decorators import require_jwt_login

from . import booking, forms, models, settings as app_settings

HISTORY_PAGE_SIZE = 10


class OwnAccountMixin:
    """Konto des angemeldeten Nextcloud-Benutzers."""

    @method_decorator(require_jwt_login)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_account(self):
        return get_object_or_404(models.Account, username=self.request.jwt_user_id, disabled=False)

    def get_booked_by(self):
        return {"booked_by_uid": self.request.jwt_user_id, "booked_by_name": self.request.jwt_user_display,
                "via_tablet": False}

    def account_url(self, name, *args):
        return reverse(f"strichliste:{name}", args=args)

    def get_success_url(self):
        return reverse("strichliste:start")


class TabletMixin:
    """Prüft die PIN des Theken-Tablets aus der URL."""

    def dispatch(self, request, *args, **kwargs):
        if not app_settings.TABLET_PIN or not secrets.compare_digest(kwargs["pin"], app_settings.TABLET_PIN):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs["pin"] = self.kwargs["pin"]
        return super().get_context_data(**kwargs)


class TabletAccountMixin(TabletMixin):
    """Konto aus der URL, gebucht vom Theken-Tablet."""

    def get_account(self):
        return get_object_or_404(models.Account, pk=self.kwargs["pk"], disabled=False)

    def get_booked_by(self):
        return {"booked_by_uid": "", "booked_by_name": "Theken-Tablet", "via_tablet": True}

    def account_url(self, name, *args):
        return reverse(f"strichliste:tablet_{name}", args=[self.kwargs["pin"], self.account.pk, *args])

    def get_success_url(self):
        return self.account_url("account")


class AccountMixin:
    """Lädt self.account über get_account() aus OwnAccountMixin oder TabletAccountMixin."""

    def dispatch(self, request, *args, **kwargs):
        self.account = self.get_account()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(account=self.account, **kwargs)


class BookingFormView(AccountMixin, FormView):
    """Formular aus Buttons auf der Kontoseite, Fehler landen als Meldung dort."""
    http_method_names = ["post"]

    def form_invalid(self, form):
        messages.error(self.request, "Dieser Betrag ist nicht vorgesehen.")
        return redirect(self.get_success_url())

    def book(self, amount, kind, label):
        try:
            tx = booking.book(self.account, amount, kind, label, self.get_booked_by())
        except ValidationError as error:
            messages.error(self.request, error.messages[0])
        else:
            verb = "abgebucht" if tx.amount < 0 else "eingezahlt"
            messages.success(self.request, f"{booking.format_cents(abs(tx.amount))} {verb}.")
        return redirect(self.get_success_url())


class AccountView(AccountMixin, TemplateView):
    template_name = "strichliste/account_detail.html"

    def get_context_data(self, **kwargs):
        page = Paginator(self.account.transactions.all(), HISTORY_PAGE_SIZE).get_page(self.request.GET.get("seite"))
        for tx in page:
            if booking.can_revert(tx):
                tx.revert_url = self.account_url("revert", tx.pk)

        warn_progress = None
        if self.account.balance < 0:
            warn_progress = min(100, round(self.account.balance / app_settings.WARN_BELOW * 100))

        return super().get_context_data(
            page=page,
            warn_progress=warn_progress,
            warn_remaining=self.account.balance - app_settings.WARN_BELOW,
            dispense_buttons=models.DispenseButton.objects.all(),
            spend_url=self.account_url("spend"),
            transfer_url=self.account_url("transfer") if app_settings.TRANSFERS_ENABLED else None,
            app_settings=app_settings,
            **kwargs,
        )


class SpendView(BookingFormView):
    form_class = forms.SpendForm

    def form_valid(self, form):
        button = form.cleaned_data["button"]
        return self.book(-button.cents, models.Transaction.KIND_DISPENSE,
                         f"{button.label} ({booking.format_cents(button.cents)})")


class TransferView(AccountMixin, FormView):
    form_class = forms.TransferForm
    template_name = "strichliste/transfer_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not app_settings.TRANSFERS_ENABLED:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {"source": self.account, **super().get_form_kwargs()}

    def form_valid(self, form):
        try:
            booking.transfer(self.account, form.cleaned_data["target"], form.cleaned_data["amount"],
                             form.cleaned_data["comment"], self.get_booked_by())
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, f"{booking.format_cents(form.cleaned_data['amount'])} an "
                                       f"{form.cleaned_data['target'].name} überwiesen.")
        return super().form_valid(form)


class RevertView(AccountMixin, View):
    def post(self, request, *args, tx, **kwargs):
        tx = get_object_or_404(models.Transaction, pk=tx, account=self.account)
        try:
            booking.revert(tx, self.get_booked_by()["booked_by_name"])
        except PermissionDenied:
            messages.error(request, "Diese Buchung kann nicht mehr storniert werden.")
        else:
            messages.success(request, f"Buchung „{tx.label}“ storniert.")
        return redirect(self.get_success_url())


class PaypalView(TemplateView):
    template_name = "strichliste/paypal.html"

    def get_context_data(self, **kwargs):
        if not app_settings.PAYPAL_LINK:
            raise Http404
        qr_code = segno.make(app_settings.PAYPAL_LINK, error="m").svg_data_uri(scale=6, border=2)
        return super().get_context_data(qr_code=qr_code, **kwargs)


# Nextcloud-Login

class StartView(OwnAccountMixin, AccountView):
    """Eigenes Konto, ohne Konto die Auswahl der noch nicht zugeordneten Konten."""

    def get_account(self):
        return models.Account.objects.filter(username=self.request.jwt_user_id, disabled=False).first()

    def get(self, request, *args, **kwargs):
        if self.account is None:
            return render(request, "strichliste/start_unassigned.html", {
                "unassigned": models.Account.objects.filter(username__isnull=True, disabled=False),
            })
        return super().get(request, *args, **kwargs)


def is_unassigned(request):
    return not models.Account.objects.filter(username=request.jwt_user_id).exists()


class AssignUserView(FormView):
    form_class = forms.AssignAccountForm
    template_name = "strichliste/assign_user_form.html"
    success_url = reverse_lazy("strichliste:start")

    # only allow this view for unassigned nextcloud-users
    @method_decorator(require_jwt_login)
    def dispatch(self, request, *args, **kwargs):
        if not is_unassigned(request):
            return redirect("strichliste:start")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        account = form.cleaned_data["account"]
        account.username = self.request.jwt_user_id
        account.name = self.request.jwt_user_display
        account.save(update_fields=["username", "name"])
        messages.success(self.request, "Das Konto ist jetzt mit deinem Nextcloud-Zugang verknüpft.")
        return super().form_valid(form)


@require_jwt_login
@require_POST
def create_user_unassigned(request):
     models.Account.objects.create(username=request.jwt_user_id,
                                   name=request.jwt_user_display)
     messages.success(self.request, "Für dich wurde ein neues Konto eingerichtet.")
     return redirect("strichliste:start")


class OwnSpendView(OwnAccountMixin, SpendView):
    pass


class OwnTransferView(OwnAccountMixin, TransferView):
    pass


class OwnRevertView(OwnAccountMixin, RevertView):
    pass


# Theken-Tablet

class TabletAccountListView(TabletMixin, ListView):
    template_name = "strichliste/account_list.html"
    queryset = models.Account.objects.filter(disabled=False)

    def get_context_data(self, **kwargs):
        accounts = list(self.object_list)
        for account in accounts:
            account.debt = account.balance <= app_settings.WARN_BELOW
        return super().get_context_data(
            active=[account for account in accounts if not account.is_stale()],
            stale=[account for account in accounts if account.is_stale()],
            app_settings=app_settings,
            **kwargs,
        )


class TabletCreateExternView(TabletMixin, FormView):
    form_class = forms.ExternForm
    template_name = "strichliste/extern_form.html"

    def form_valid(self, form):
        account = form.save()
        messages.success(self.request, f"{account.name} wurde als externe Person angelegt.")
        return redirect("strichliste:tablet_account", self.kwargs["pin"], account.pk)


class TabletAccountView(TabletAccountMixin, AccountView):
    def get_context_data(self, **kwargs):
        return super().get_context_data(credit_url=self.account_url("credit"), **kwargs)


class TabletCreditView(TabletAccountMixin, BookingFormView):
    form_class = forms.CreditForm

    def form_valid(self, form):
        cents = form.cleaned_data["amount"]
        return self.book(cents, models.Transaction.KIND_DEPOSIT, f"Einzahlung bar {booking.format_cents(cents)}")


class TabletSpendView(TabletAccountMixin, SpendView):
    pass


class TabletTransferView(TabletAccountMixin, TransferView):
    pass


class TabletRevertView(TabletAccountMixin, RevertView):
    pass
