import string
from django.core.exceptions import ValidationError


def validate_kartenfuehrerschein_nummer(nummer: str) -> str:
    nummer = nummer.strip().upper()

    if len(nummer) != 11:
        raise ValidationError("Führerscheinnummer ist nicht 11-Stellig")

    summe = 0
    for ziffer, multiplier in zip(nummer[:9], [9, 8, 7, 6, 5, 4, 3, 2, 1], strict=True):
        try:
            summe += (string.digits + string.ascii_uppercase).index(ziffer) * multiplier
        except ValueError as error:
            raise ValidationError(f"Ungültige Zeichen {error} in Führerscheinnummer")

    rest = summe % 11
    if nummer[9] != (string.digits + "X")[summe % 11]:
        raise ValidationError("Prüfziffer in Führerscheinnummer ungültig")

    if nummer[10] not in string.ascii_uppercase + string.digits:
        raise ValidationError("Ungültige Zeichen in Führerscheinnummer")

    return nummer
