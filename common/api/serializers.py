from django.contrib.humanize.templatetags.humanize import naturaltime
from django.utils.translation import get_language
from rest_framework import serializers


class NaturalTimeField(serializers.ReadOnlyField):

    def to_representation(self, value):
        if value is None:
            return None

        out = naturaltime(value)
        if get_language() == 'uz':
            out = (out.replace('weeks', 'hafta')
                   .replace('week', 'hafta')
                   .replace('days', 'kun')
                   .replace('day', 'kun')
                   .replace('months', 'oy')
                   .replace('month', 'oy')
                   .replace('years', 'yil')
                   .replace('year', 'yil'))
        return out


class EmptySerializer(serializers.Serializer):
    pass
