from rest_framework import serializers

from apps.restaurants.helpers import get_restaurant_model

Restaurant = get_restaurant_model()


class PosRestaurantCodeSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=6, max_length=6, trim_whitespace=True)

    def validate(self, attrs):
        code = attrs['code'].strip()
        restaurant = Restaurant.objects.filter(auth_code=code).first()
        if restaurant is None or not restaurant.is_active:
            raise serializers.ValidationError({'code': 'Restaurant code is invalid.'})

        attrs['restaurant'] = restaurant
        return attrs


class PosRestaurantContextSerializer(serializers.ModelSerializer):
    restaurant_id = serializers.UUIDField(source='id', read_only=True)
    restaurant_name = serializers.CharField(source='name', read_only=True)

    class Meta:
        model = Restaurant
        fields = ('restaurant_id', 'restaurant_name')
