"""Sale-unit contract shared by catalog, orders, inventory and generated clients."""
import json
from decimal import Decimal
from pathlib import Path

from django.db import models

SALE_UNITS = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
SaleUnit = models.TextChoices('SaleUnit', [(rule['enum'], (key, rule['name'])) for key, rule in SALE_UNITS.items()])


def sale_unit_rule(unit):
    return SALE_UNITS[unit or SaleUnit.PIECE]


def sale_quantity_step(unit):
    return Decimal(str(sale_unit_rule(unit)['step']))


def valid_sale_quantity(quantity, unit, *, allow_zero=False):
    return (quantity is not None and quantity.is_finite()
            and quantity >= (Decimal('0') if allow_zero else sale_quantity_step(unit))
            and quantity <= Decimal('999999999.999')
            and quantity % sale_quantity_step(unit) == 0)


def sale_unit_label(unit, locale='uz', *, piece_label=None):
    rule = sale_unit_rule(unit)
    if piece_label is not None and not rule['quantityInput']:
        return piece_label
    return rule['labels'].get(locale, rule['labels']['uz'])
