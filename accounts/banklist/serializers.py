from rest_framework import serializers
from .models import Bank, BankAccount
from django.contrib.auth import authenticate
from .models import User, Company


class BankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bank
        fields = '__all__'


class BankAccountSerializer(serializers.ModelSerializer):
    bank_name = serializers.CharField(source='bank.bank_name', read_only=True)
    bank_short_name = serializers.CharField(source='bank.short_name', read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            'id', 'bank', 'bank_name', 'bank_short_name',
            'account_holder_name', 'account_number', 'ifsc_code',
            'bank_folder_id', 'statement_folder_id', 'drive_link',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['bank_folder_id', 'statement_folder_id', 'drive_link']


class RegisterSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255)
    full_name    = serializers.CharField(max_length=255)
    email        = serializers.EmailField()
    password     = serializers.CharField(min_length=8, write_only=True)
    confirm_password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('Email already registered')
        return value

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match'})
        return data

    def create(self, validated_data):
        company = Company.objects.create(name=validated_data['company_name'])
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            full_name=validated_data['full_name'],
            company=company,
        )
        return user


class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data['email'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Invalid email or password')
        if not user.is_active:
            raise serializers.ValidationError('Account is disabled')
        data['user'] = user
        return data

