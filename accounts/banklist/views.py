from django.shortcuts import render

# Create your views here.
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Bank
from .serializers import BankSerializer

@api_view(['GET'])
def search_banks(request):

    search = request.GET.get('search', '')

    banks = Bank.objects.filter(
        Q(bank_name__icontains=search) |
        Q(short_name__icontains=search)
    )[:10]

    serializer = BankSerializer(banks, many=True)

    return Response(serializer.data)