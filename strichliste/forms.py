from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError

from . import models


class ExternForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contact"].required = True
        self.fields["contact"].queryset = models.Account.objects.filter(kind=models.Account.KIND_NEXTCLOUD, disabled=False)
        self.fields["name"].widget.attrs["placeholder"] = "Vor- und Nachname"
        self.fields["note"].widget.attrs["placeholder"] = "z.B. FF Arheilgen"

    class Meta:
        model = models.Account
        fields = ["name", "tags", "contact", "note"]
        widgets = {"tags": forms.CheckboxSelectMultiple}


def parse_euro(value: str) -> int:
    """Wandelt eine Eingabe wie „1,10“ in Cent um."""
    try:
        amount = Decimal(value.replace("€", "").strip().replace(",", "."))
    except InvalidOperation as error:
        raise ValidationError("Bitte einen Betrag wie 1,10 eingeben.") from error
    cents = amount * 100
    if not cents.is_finite() or cents <= 0 or cents != int(cents):
        raise ValidationError("Bitte einen positiven Betrag mit höchstens zwei Nachkommastellen eingeben.")
    return int(cents)


class TransferForm(forms.Form):
    target = forms.ModelChoiceField(queryset=models.Account.objects.none(), label="An")
    amount = forms.CharField(label="Betrag in €", initial="5,00")
    comment = forms.CharField(label="Verwendungszweck", required=False, max_length=100)

    def __init__(self, *args, source, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].queryset = models.Account.objects.filter(disabled=False).exclude(pk=source.pk)

    def clean_amount(self):
        return parse_euro(self.cleaned_data["amount"])
