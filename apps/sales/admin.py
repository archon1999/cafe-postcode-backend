from django.contrib import admin

from .models import Order, OrderItem, OrderItemModifier, OrderItemNote

admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(OrderItemNote)
admin.site.register(OrderItemModifier)
