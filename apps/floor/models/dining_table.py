from django.db import models

from common.models import BaseModel

from .hall import Hall
from .zone_or_cabin import ZoneOrCabin


class DiningTable(BaseModel):
    SHAPE_VARIANTS_BY_SEAT_COUNT = {
        2: ('seat2_horizontal', 'seat2_vertical'),
        3: ('seat3_triangle',),
        4: ('seat4_square', 'seat4_horizontal', 'seat4_vertical'),
        5: ('seat5_horizontal', 'seat5_vertical'),
        6: ('seat6_horizontal', 'seat6_vertical'),
    }
    DEFAULT_SHAPE_VARIANT_BY_SEAT_COUNT = {
        2: 'seat2_horizontal',
        3: 'seat3_triangle',
        4: 'seat4_square',
        5: 'seat5_horizontal',
        6: 'seat6_horizontal',
    }

    class Shape(models.TextChoices):
        SQUARE = 'square', 'Square'
        RECTANGLE = 'rectangle', 'Rectangle'
        ROUND = 'round', 'Round'
        OVAL = 'oval', 'Oval'

    class ShapeVariant(models.TextChoices):
        SEAT2_HORIZONTAL = 'seat2_horizontal', '2 Seat Horizontal'
        SEAT2_VERTICAL = 'seat2_vertical', '2 Seat Vertical'
        SEAT3_TRIANGLE = 'seat3_triangle', '3 Seat Triangle'
        SEAT4_SQUARE = 'seat4_square', '4 Seat Square'
        SEAT4_HORIZONTAL = 'seat4_horizontal', '4 Seat Horizontal'
        SEAT4_VERTICAL = 'seat4_vertical', '4 Seat Vertical'
        SEAT5_HORIZONTAL = 'seat5_horizontal', '5 Seat Horizontal'
        SEAT5_VERTICAL = 'seat5_vertical', '5 Seat Vertical'
        SEAT6_HORIZONTAL = 'seat6_horizontal', '6 Seat Horizontal'
        SEAT6_VERTICAL = 'seat6_vertical', '6 Seat Vertical'

    class Status(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        OCCUPIED = 'occupied', 'Occupied'
        RESERVED = 'reserved', 'Reserved'
        BLOCKED = 'blocked', 'Blocked'

    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name='tables')
    zone = models.ForeignKey(
        ZoneOrCabin,
        on_delete=models.SET_NULL,
        related_name='tables',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    table_number = models.PositiveIntegerField()
    seat_count = models.PositiveIntegerField(default=4)
    shape = models.CharField(max_length=20, choices=Shape.choices, default=Shape.SQUARE)
    shape_variant = models.CharField(
        max_length=32,
        choices=ShapeVariant.choices,
        default=ShapeVariant.SEAT4_SQUARE,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    position_x = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    position_y = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    width = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    height = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    rotation = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    service_fee_enabled = models.BooleanField(default=False)
    service_fee_percent = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('table_number', 'name')
        unique_together = ('hall', 'table_number')

    def __str__(self):
        return self.name

    @classmethod
    def get_supported_seat_counts(cls):
        return tuple(cls.SHAPE_VARIANTS_BY_SEAT_COUNT.keys())

    @classmethod
    def get_supported_variants_for_seat_count(cls, seat_count: int):
        return cls.SHAPE_VARIANTS_BY_SEAT_COUNT.get(seat_count, ())

    @classmethod
    def get_default_shape_variant(cls, seat_count: int):
        return cls.DEFAULT_SHAPE_VARIANT_BY_SEAT_COUNT.get(seat_count, cls.ShapeVariant.SEAT4_SQUARE)

    @classmethod
    def infer_shape_from_variant(cls, shape_variant: str):
        if shape_variant in {
            cls.ShapeVariant.SEAT2_VERTICAL,
            cls.ShapeVariant.SEAT3_TRIANGLE,
            cls.ShapeVariant.SEAT4_SQUARE,
        }:
            return cls.Shape.SQUARE
        return cls.Shape.RECTANGLE
