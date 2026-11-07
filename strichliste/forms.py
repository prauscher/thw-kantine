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


class DispenseButtonForm(forms.ModelForm):
    price = forms.CharField(label="Preis in €")
    field_order = ["label", "price", "position"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["price"] = f"{self.instance.cents / 100:.2f}".replace(".", ",")

    def clean_price(self):
        return parse_euro(self.cleaned_data["price"])

    def save(self, commit=True):
        self.instance.cents = self.cleaned_data["price"]
        return super().save(commit)

    class Meta:
        model = models.DispenseButton
        fields = ["label", "position"]


class TransferForm(forms.Form):
    target = forms.ModelChoiceField(queryset=models.Account.objects.none(), label="An")
    amount = forms.CharField(label="Betrag in €", initial="5,00")
    comment = forms.CharField(label="Verwendungszweck", required=False, max_length=100)

    def __init__(self, *args, source, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].queryset = models.Account.objects.filter(disabled=False).exclude(pk=source.pk)

    def clean_amount(self):
        return parse_euro(self.cleaned_data["amount"])


class ConfigForm(forms.ModelForm):
    class Meta:
        model = models.Config
        exclude = ["test_mode"]


class TagForm(forms.ModelForm):
    class Meta:
        model = models.Tag
        fields = ["label"]


class PinField(forms.CharField):
    def __init__(self, **kwargs):
        super().__init__(min_length=4, max_length=12, widget=forms.PasswordInput(attrs={
            "inputmode": "numeric", "autocomplete": "off", "pattern": "[0-9]*"}), **kwargs)

    def clean(self, value):
        value = super().clean(value)
        if value and not value.isdigit():
            raise ValidationError("Die PIN darf nur aus Ziffern bestehen.")
        return value


class TabletCreateForm(forms.ModelForm):
    pin = PinField(label="PIN", help_text="4 bis 12 Ziffern. Wird einmalig auf dem Tablet eingegeben.")

    class Meta:
        model = models.Tablet
        fields = ["label"]


class TabletPinForm(forms.Form):
    pin = PinField(label="PIN")


class LinkForm(forms.Form):
    username = forms.CharField(label="Nextcloud-Benutzername", max_length=50)
    name = forms.CharField(label="Anzeigename", max_length=100, required=False,
                           help_text="Leer lassen, um den bisherigen Namen zu behalten. Wird beim nächsten Login aus Nextcloud übernommen.")
