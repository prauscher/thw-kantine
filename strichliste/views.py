from io import BytesIO

import segno
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from . import booking, forms, models
from .auth import get_tablet, require_actor, require_admin, set_tablet_cookie

HISTORY_PAGE_SIZE = 10


def _sl_redirect(request, name, *args):
    if request.tablet_token:
        return redirect(f"strichliste:tablet_{name}", request.tablet_token, *args)
    return redirect(f"strichliste:{name}", *args)


def _context(request, **kwargs):
    return {"config": models.Config.get(), "actor": request.actor, "is_tablet": request.actor.is_tablet, **kwargs}


@require_actor
def start(request):
    if request.actor.is_tablet:
        return _sl_redirect(request, "konten")
    return _account_page(request, request.actor.account.pk, own=True)


@require_actor
def accounts(request):
    config = models.Config.get()
    accounts = list(models.Account.objects.filter(disabled=False).prefetch_related("tags"))
    for account in accounts:
        account.stale = account.is_stale(config)
        account.debt = account.balance <= config.warn_below
    return render(request, "strichliste/account_grid.html", _context(
        request,
        accounts=accounts,
        counts={
            "aktiv": sum(not a.stale for a in accounts),
            "inaktiv": sum(a.stale for a in accounts),
            "extern": sum(a.is_extern for a in accounts),
            "ausgleichen": sum(a.debt for a in accounts),
        },
    ))


@require_actor
def account_detail(request, pk):
    return _account_page(request, pk)


def _account_page(request, pk, own=False):
    account = get_object_or_404(models.Account, pk=pk, disabled=False)
    actor = request.actor
    config = models.Config.get()
    own = own or (actor.account is not None and actor.account.pk == account.pk)
    can_book = actor.can_book(account)

    if request.method == "POST":
        if not can_book:
            raise PermissionDenied
        try:
            tx = booking.book_step(account, request.POST.get("action", ""), int(request.POST.get("value", 0)), actor)
        except (ValidationError, ValueError) as error:
            messages.error(request, error.messages[0] if isinstance(error, ValidationError) else "Ungültiger Betrag.")
        else:
            verb = "abgebucht" if tx.amount < 0 else "eingezahlt"
            messages.success(request, f"{booking.format_cents(abs(tx.amount))} {verb}.")
        if own and not actor.is_tablet:
            return redirect("strichliste:start")
        return _sl_redirect(request, "konto", account.pk)

    page = None
    if can_book:
        page = Paginator(account.transactions.all(), HISTORY_PAGE_SIZE).get_page(request.GET.get("seite"))
        for tx in page:
            tx.can_revert = actor.can_revert(tx, config)
            tx.by_me = (tx.tablet_id == actor.tablet.pk) if actor.is_tablet else (tx.tablet_id is None and tx.booked_by_uid == actor.uid)

    warn_progress = None
    if account.balance < 0:
        warn_progress = min(100, round(account.balance / config.warn_below * 100))

    return render(request, "strichliste/account_detail.html", _context(
        request,
        account=account,
        own=own,
        can_book=can_book,
        page=page,
        warn_progress=warn_progress,
        warn_remaining=account.balance - config.warn_below,
        dispense_buttons=models.DispenseButton.objects.all(),
        can_edit=account.is_extern and (actor.is_admin or (actor.account is not None and account.contact_id == actor.account.pk)),
    ))


@require_POST
@require_actor
def revert(request, pk):
    tx = get_object_or_404(models.Transaction, pk=pk)
    try:
        booking.revert(tx, request.actor)
    except PermissionDenied:
        messages.error(request, "Diese Buchung kann nicht mehr storniert werden.")
    else:
        messages.success(request, f"Buchung „{tx.label}“ storniert.")
    if request.actor.account is not None and tx.account_id == request.actor.account.pk:
        return redirect("strichliste:start")
    return _sl_redirect(request, "konto", tx.account_id)


@require_actor
def transfer(request, pk):
    if not models.Config.get().transfers_enabled:
        raise Http404
    source = get_object_or_404(models.Account, pk=pk, disabled=False)
    if not request.actor.can_book(source):
        raise PermissionDenied

    form = forms.TransferForm(request.POST or None, source=source, initial={"target": request.GET.get("an")})
    if request.method == "POST" and form.is_valid():
        try:
            booking.transfer(source, form.cleaned_data["target"], form.cleaned_data["amount"],
                             form.cleaned_data["comment"], request.actor)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"{booking.format_cents(form.cleaned_data['amount'])} an {form.cleaned_data['target'].name} überwiesen.")
            return _sl_redirect(request, "konto", source.pk)

    return render(request, "strichliste/transfer_form.html", _context(request, account=source, form=form))


@require_actor
def extern_form(request, pk=None):
    account = None
    if pk is not None:
        account = get_object_or_404(models.Account, pk=pk, kind=models.Account.KIND_EXTERN)
        actor = request.actor
        if not (actor.is_admin or (actor.account is not None and account.contact_id == actor.account.pk)):
            raise PermissionDenied

    initial = {}
    if account is None and request.actor.account is not None:
        initial["contact"] = request.actor.account
    form = forms.ExternForm(request.POST or None, instance=account, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.instance.kind = models.Account.KIND_EXTERN
        account = form.save()
        messages.success(request, f"{account.name} wurde gespeichert." if pk else f"{account.name} wurde als externe Person angelegt.")
        return _sl_redirect(request, "konto", account.pk)

    return render(request, "strichliste/extern_form.html", _context(request, account=account, form=form))


@require_actor
def paypal(request):
    config = models.Config.get()
    if request.actor.is_tablet or not config.paypal_link:
        raise Http404
    buffer = BytesIO()
    segno.make(config.paypal_link, error="m").save(buffer, kind="svg", scale=6, border=2, xmldecl=False, svgns=True)
    return render(request, "strichliste/paypal.html", _context(request, qr_svg=mark_safe(buffer.getvalue().decode())))


def tablet_pin(request, token):
    tablet = get_tablet(token)
    form = forms.TabletPinForm(request.POST or None)
    if request.method == "POST" and not tablet.is_locked and form.is_valid():
        if tablet.check_pin(form.cleaned_data["pin"]):
            response = redirect("strichliste:tablet_konten", token)
            set_tablet_cookie(response, request, tablet)
            return response
        if not tablet.is_locked:
            form.add_error("pin", "Die PIN ist falsch.")

    return render(request, "strichliste/tablet_pin.html", {"config": models.Config.get(), "tablet": tablet, "form": form})


# Verwaltung

@require_admin
def admin_accounts(request):
    config = models.Config.get()
    accounts = models.Account.objects.prefetch_related("tags").select_related("contact").order_by("balance", "name")
    totals = models.Account.objects.aggregate(
        positive=Sum("balance", filter=Q(balance__gt=0), default=0),
        negative=Sum("balance", filter=Q(balance__lt=0), default=0),
        debt=Count("pk", filter=Q(balance__lte=config.warn_below)),
        extern=Count("pk", filter=Q(kind=models.Account.KIND_EXTERN)),
        legacy=Count("pk", filter=Q(kind=models.Account.KIND_LEGACY)),
    )
    return render(request, "strichliste/admin_accounts.html", _context(request, accounts=accounts, totals=totals, tab="konten"))


@require_admin
def admin_link(request, pk):
    account = get_object_or_404(models.Account, pk=pk, kind__in=[models.Account.KIND_EXTERN, models.Account.KIND_LEGACY])
    form = forms.LinkForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        merged = booking.link_account(account, form.cleaned_data["username"].strip(), form.cleaned_data["name"].strip() or None)
        messages.success(request, f"Konto ist jetzt mit dem Nextcloud-Benutzer {merged.username} verknüpft.")
        return redirect("strichliste:admin_konten")
    return render(request, "strichliste/admin_link.html", _context(request, account=account, form=form, tab="konten"))


@require_POST
@require_admin
def admin_account_action(request, pk):
    account = get_object_or_404(models.Account, pk=pk)
    action = request.POST.get("action")
    if action == "extern" and account.kind == models.Account.KIND_LEGACY:
        account.kind = models.Account.KIND_EXTERN
        account.contact = request.actor.account
        account.save(update_fields=["kind", "contact"])
        messages.success(request, f"{account.name} wird jetzt als externe Person geführt.")
    elif action in ("disable", "enable"):
        account.disabled = action == "disable"
        account.save(update_fields=["disabled"])
        messages.success(request, f"{account.name} wurde {'deaktiviert' if account.disabled else 'wieder aktiviert'}.")
    return redirect("strichliste:admin_konten")


@require_admin
def admin_buttons(request):
    if request.method == "POST":
        if "delete" in request.POST:
            models.DispenseButton.objects.filter(pk=request.POST["delete"]).delete()
            return redirect("strichliste:admin_buttons")
        instance = get_object_or_404(models.DispenseButton, pk=request.POST["pk"]) if request.POST.get("pk") else None
        form = forms.DispenseButtonForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, f"Button „{form.instance.label}“ gespeichert.")
        else:
            messages.error(request, " ".join(error for errors in form.errors.values() for error in errors))
        return redirect("strichliste:admin_buttons")

    return render(request, "strichliste/admin_buttons.html", _context(
        request, buttons=models.DispenseButton.objects.all(),
        next_position=models.DispenseButton.objects.count() + 1, tab="buttons"))


@require_admin
def admin_tags(request):
    form = forms.TagForm(request.POST or None)
    if request.method == "POST":
        if "delete" in request.POST:
            models.Tag.objects.filter(pk=request.POST["delete"]).delete()
            return redirect("strichliste:admin_tags")
        if form.is_valid():
            form.save()
            return redirect("strichliste:admin_tags")
    tags = models.Tag.objects.annotate(count=Count("account"))
    return render(request, "strichliste/admin_tags.html", _context(request, tags=tags, form=form, tab="tags"))


@require_admin
def admin_config(request):
    form = forms.ConfigForm(request.POST or None, instance=models.Config.get())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Einstellungen gespeichert.")
        return redirect("strichliste:admin_einstellungen")
    return render(request, "strichliste/admin_config.html", _context(request, form=form, tab="einstellungen"))


@require_admin
def admin_tablets(request):
    form = forms.TabletCreateForm(request.POST or None)
    if request.method == "POST":
        tablet = None
        if "pk" in request.POST:
            tablet = get_object_or_404(models.Tablet, pk=request.POST["pk"])
        action = request.POST.get("action")
        if tablet and action == "logout":
            tablet.session_version += 1
            tablet.save(update_fields=["session_version"])
            messages.success(request, f"Alle Geräte von „{tablet.label}“ wurden abgemeldet. Dort muss die PIN neu eingegeben werden.")
        elif tablet and action in ("disable", "enable"):
            tablet.active = action == "enable"
            tablet.save(update_fields=["active"])
            messages.success(request, f"„{tablet.label}“ wurde {'aktiviert' if tablet.active else 'gesperrt'}.")
        elif tablet and action == "pin":
            pin_form = forms.TabletPinForm(request.POST)
            if pin_form.is_valid():
                tablet.set_pin(pin_form.cleaned_data["pin"])
                tablet.save()
                messages.success(request, f"Neue PIN für „{tablet.label}“ gesetzt. Angemeldete Geräte müssen sie neu eingeben.")
            else:
                messages.error(request, "Die PIN muss aus 4 bis 12 Ziffern bestehen.")
        elif tablet is None and form.is_valid():
            form.instance.set_pin(form.cleaned_data["pin"])
            form.save()
            messages.success(request, f"Tablet-Zugang „{form.instance.label}“ angelegt.")
        else:
            return _render_tablets(request, form)
        return redirect("strichliste:admin_tablets")
    return _render_tablets(request, form)


def _render_tablets(request, form):
    tablets = list(models.Tablet.objects.order_by("label"))
    for tablet in tablets:
        tablet.url = request.build_absolute_uri(reverse("strichliste:tablet_start", args=[tablet.token]))
    return render(request, "strichliste/admin_tablets.html", _context(request, tablets=tablets, form=form, tab="tablets"))
