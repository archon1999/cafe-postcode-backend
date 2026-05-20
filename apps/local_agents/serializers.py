from rest_framework import serializers

from apps.restaurants.helpers import get_restaurant_model

Restaurant = get_restaurant_model()


class LocalAgentRestaurantCodeSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=6, max_length=6, trim_whitespace=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    version = serializers.CharField(required=False, allow_blank=True, max_length=50)

    def validate(self, attrs):
        restaurant = Restaurant.objects.filter(auth_code=attrs['code'].strip(), is_active=True).first()
        if restaurant is None:
            raise serializers.ValidationError({'code': 'Restaurant code is invalid.'})
        attrs['restaurant'] = restaurant
        return attrs


class LocalAgentStatusSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    restaurant_id = serializers.UUIDField(source='restaurant.id')
    restaurant_name = serializers.CharField(source='restaurant.name')
    name = serializers.CharField()
    status = serializers.CharField()
    last_seen_at = serializers.DateTimeField(allow_null=True)
    version = serializers.CharField()
    capabilities = serializers.JSONField()
