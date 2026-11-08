from io import BytesIO

import segno
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from . import booking, config as conf, forms, models
from .auth import require_actor

HISTORY_PAGE_SIZE = 10


def _sl_redirect(request, name, *args):
    if request.tablet_pin:
        return redirect(f"strichliste:tablet_{name}", request.tablet_pin, *args)
    return redirect(f"strichliste:{name}", *args)


def _context(request, **kwargs):
    return {"config": conf.get(), "actor": request.actor, "is_tablet": request.actor.is_tablet, **kwargs}


@require_actor
def start(request):
    if request.actor.is_tablet:
        return _sl_redirect(request, "konten")
    return _account_page(request, request.actor.account.pk, own=True)


@require_actor
def accounts(request):
    config = conf.get()
    accounts = list(models.Account.objects.filter(disabled=False).prefetch_related("tags"))
    for account in accounts:
        account.stale = account.is_stale(config.stale_days)
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
    config = conf.get()
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
            tx.by_me = tx.via_tablet if actor.is_tablet else (not tx.via_tablet and tx.booked_by_uid == actor.uid)

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
        can_edit=account.is_extern and actor.account is not None and account.contact_id == actor.account.pk,
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
    if not conf.get().transfers_enabled:
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
        if actor.account is None or account.contact_id != actor.account.pk:
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
    config = conf.get()
    if request.actor.is_tablet or not config.paypal_link:
        raise Http404
    buffer = BytesIO()
    segno.make(config.paypal_link, error="m").save(buffer, kind="svg", scale=6, border=2, xmldecl=False, svgns=True)
    return render(request, "strichliste/paypal.html", _context(request, qr_svg=mark_safe(buffer.getvalue().decode())))
