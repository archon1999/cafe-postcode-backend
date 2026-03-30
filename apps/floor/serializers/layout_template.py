from rest_framework import serializers

from apps.floor.models import LayoutTemplate


class LayoutTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LayoutTemplate
        fields = ('id', 'name', 'description', 'payload', 'is_default')
