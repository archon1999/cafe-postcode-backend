from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import PosRestaurantCodeSerializer, PosRestaurantContextSerializer


class PosRestaurantCodeView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PosRestaurantCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restaurant = serializer.validated_data['restaurant']
        return Response(PosRestaurantContextSerializer(restaurant).data)
