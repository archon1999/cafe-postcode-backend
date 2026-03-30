from django.contrib import admin

from .models import Order, OrderItem, OrderItemNote, Payment, Receipt

admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(OrderItemNote)
admin.site.register(Payment)
admin.site.register(Receipt)

