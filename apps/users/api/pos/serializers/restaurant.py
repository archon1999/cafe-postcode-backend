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
    pos_auth_background_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Restaurant
        fields = (
            'restaurant_id',
            'restaurant_name',
            'phone',
            'social',
            'address',
            'pos_auth_background_image_url',
            'service_fee_enabled',
            'service_fee_percent',
            'vat_enabled',
            'vat_percent',
        )

    def get_pos_auth_background_image_url(self, instance):
        image = getattr(instance, 'pos_auth_background_image', None)
        if image and getattr(image, 'name', ''):
            return image.url
        return None
