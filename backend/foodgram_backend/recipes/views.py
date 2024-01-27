import logging
from venv import logger

from django.db.models import Sum
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from users.permissions import IsAdminOrReadOnly, UsersAuthPermission

from recipes.filters import IngredientFilterSet, RecipeFilterSet
from recipes.models import Favorites, Ingredient, MeasurementUnit, Recipe, RecipeIngredient, Tag, ShoppingCart
from recipes.serializers import (IngredientSerializer, LimitedRecipeSerializer,
                                 MeasurementUnitSerializer, RecipeSerializer,
                                 ShoppingCartSerializer, TagSerializer)

logging.basicConfig(level=logging.INFO)


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    pagination_class = None


class MeasurementUnitViewSet(viewsets.ModelViewSet):
    queryset = MeasurementUnit.objects.all()
    serializer_class = MeasurementUnitSerializer


class RecipeViewSet(viewsets.ModelViewSet):
    queryset = Recipe.objects.all()
    serializer_class = RecipeSerializer
    pagination_class = LimitOffsetPagination
    filter_backends = (DjangoFilterBackend,)
    filterset_class = RecipeFilterSet

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def mark_recipe(self, request_type):
        self.serializer_class = LimitedRecipeSerializer
        try:
            recipe = self.get_object()
        except Exception as err:
            logger.error(f'RECIPE NOT FOUND: {err}\n')
            return Response(
                        {'error': 'No Recipe matches the given query.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
        user = self.request.user
        if request_type == 'favorite':
            favorite, created = Favorites.objects.get_or_create(
                recipe=recipe, user=user
            )
        elif request_type == 'shopping_cart':
            shopping_cart, created = ShoppingCart.objects.get_or_create(
                recipe=recipe, user=user
            )

        #  !!!!! Temporary solution for endopoint download_shopping_cart
        elif request_type == 'download_shopping_cart':
            created = True
        if created:
            response_status = status.HTTP_201_CREATED
            return Response(
                LimitedRecipeSerializer(recipe).data,
                status=response_status
            )
        else:
            return Response(
                        {'error': 'Recipe is already in favorites.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

    @action(
        detail=True,
        methods=['post'],
        url_path='favorite',
        permission_classes=[UsersAuthPermission]
    )
    def favorite(self, request, pk=None):
        return self.mark_recipe('favorite')

    @action(
        detail=True,
        methods=['post'],
        url_path='shopping_cart',
        permission_classes=[UsersAuthPermission]
    )
    def shopping_cart(self, request, pk=None):
        return self.mark_recipe('shopping_cart')

    @action(
        detail=False,
        methods=['get'],
        url_path='download_shopping_cart',
        permission_classes=[UsersAuthPermission]
    )
    def download_shopping_cart(self, request, pk=None):
        logger.info(f'~~~ START download_shopping_cart')
        self.serializer_class = ShoppingCartSerializer

        user = self.request.user
        logger.info(f'~~~ USER: {type(user)} | {user}')

        recipes_in_shopping_cart = ShoppingCart.objects.filter(user=user).values('recipe')
        logger.info(f'~~~ RECIPES: {recipes_in_shopping_cart}')

        ingredients = RecipeIngredient.objects.filter(recipe__in=recipes_in_shopping_cart)
        logger.info(f'~~~ INGREDIENTS: {type(ingredients)} | {ingredients}')
        
        shopping_cart = (
            ingredients
            .values('ingredient__name', 'measurement_unit__name')
            .annotate(
                total_amount=Sum('amount'),
            )
        )
        logger.info(f'~~~ SHOPPING CART: {type(shopping_cart)} | {shopping_cart}')

        current_recipes = user.recipes.all()
        serializer = ShoppingCartSerializer(shopping_cart, many=True)
        return Response(
                serializer.data,
                status=status.HTTP_200_OK
        )


class IngredientViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Ingredient.objects.all()
    serializer_class = IngredientSerializer
    # permission_classes = (IsAdminOrReadOnly, )
    pagination_class = None
    filter_backends = (DjangoFilterBackend, )
    filterset_class = IngredientFilterSet


class ImportIngredientsView(APIView):
    serializer_class = IngredientSerializer(many=True)
    permission_classes = (IsAdminOrReadOnly, )

    def post(self, request, *args, **kwargs):
        data = request.data.get('data')
        serializer = IngredientSerializer(data=data, many=True)
        new_ids = []

        if serializer.is_valid():
            for item in serializer.validated_data:
                measurement_unit_name = item.get('measurement_unit')
                ingredient_name = item.get('name')
                
                measurement_unit, status = MeasurementUnit.objects.get_or_create(
                    name=measurement_unit_name)
            
                Ingredient.objects.get_or_create(
                    name=ingredient_name,
                    measurement_unit=measurement_unit
                )
                new_ids.append(Ingredient.objects.get(name=ingredient_name).id)

            return Response(
                {'detail':
                    f'Ingredients imported successfully. Information: {new_ids}'},
                status=status.HTTP_201_CREATED)

        return Response(
            {
                'detail': f'Invalid data. Data: {data}',
                'errors': serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )