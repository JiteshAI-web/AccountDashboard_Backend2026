from django.shortcuts import render

# Create your views here.
from django.db.models import Q
from django.views.decorators.cache import cache_page
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from .models import Bank
from .models import BankAccount
from .serializers import BankSerializer, BankAccountSerializer
from rest_framework import status
from .services.google_drive_service import drive_service
from .tasks import create_drive_folder_task, upload_to_drive_task
import calendar
from datetime import datetime
import re
from celery.result import AsyncResult
from rest_framework.parsers import MultiPartParser, FormParser

from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import RegisterSerializer, LoginSerializer
MONTH_NAME_TO_NUM = {name.lower(): num for num, name in enumerate(calendar.month_name) if num}
MONTH_ABBR_TO_NUM = {abbr.lower(): num for num, abbr in enumerate(calendar.month_abbr) if num}

def detect_month_year_from_filename(filename):
    """
    Try to extract month and year from filename.
    Supports: 'Jan2026', 'January_2026', '2026-01', '01-2026', 'Statement_Jan_26'
    Returns (month, year) or (None, None)
    """
    name = filename.lower()

    # Pattern: 2026-01 or 2026_01
    match = re.search(r'(20\d{2})[-_]?(\d{1,2})\b', name)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return month, year

    # Pattern: 01-2026 or 01_2026
    match = re.search(r'\b(\d{1,2})[-_](20\d{2})', name)
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return month, year

    # Pattern: January2026, Jan_2026, Jan-26
    for mname, mnum in MONTH_NAME_TO_NUM.items():
        if mname in name:
            year_match = re.search(rf'{mname}[-_]?(\d{{2,4}})', name)
            if year_match:
                year_str = year_match.group(1)
                year = int(year_str) if len(year_str) == 4 else 2000 + int(year_str)
                return mnum, year

    for mabbr, mnum in MONTH_ABBR_TO_NUM.items():
        if mabbr and mabbr in name:
            year_match = re.search(rf'{mabbr}[-_]?(\d{{2,4}})', name)
            if year_match:
                year_str = year_match.group(1)
                year = int(year_str) if len(year_str) == 4 else 2000 + int(year_str)
                return mnum, year

    return None, None


def _get_company_name(request):
    """Return the logged-in user's company name for Drive folder isolation.
    Falls back to user's full_name if no company is assigned."""
    try:
        user = request.user
        if user.company:
            return user.company.name
        # Fallback: use full_name so user still gets isolated folder
        return user.full_name or user.email
    except Exception as e:
        print(f"⚠️ _get_company_name error: {e}")
        return None


@cache_page(60)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_banks(request):
    search_term = request.GET.get('search', '').strip()
    
    if search_term:
        banks = Bank.objects.filter(bank_name__icontains=search_term, is_active=True)
    else:
        banks = Bank.objects.filter(is_active=True)  # return all banks
    
    data = [
        {
            'bank_name': b.bank_name,
            'short_name': b.short_name,
        }
        for b in banks
    ]
    return Response(data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def init_company_folder(request):
    """
    Create (or get) the logged-in user's company folder in Google Drive,
    along with 4 default subfolders.
    """
    company_name = _get_company_name(request)

    if not company_name:
        return Response(
            {'error': 'Could not determine company/user name'},
            status=status.HTTP_400_BAD_REQUEST
        )

    result = drive_service.get_or_create_company_folder(company_name)

    if not result:
        return Response(
            {'error': 'Failed to create company folder in Google Drive'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return Response({
        'success': True,
        'message': f'Company folder ready: {company_name}',
        'company_name': company_name,
        'company_folder_id': result['company_folder_id'],
        'subfolders': result['subfolders'],
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_bank_accounts(request):
    """List all bank accounts for the logged-in user's company."""
    company = request.user.company
    if not company:
        return Response({'error': 'User has no company'}, status=400)

    accounts = BankAccount.objects.filter(company=company).select_related('bank')
    serializer = BankAccountSerializer(accounts, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_drive_folder(request):
    """Create Google Drive folder for selected bank and save to DB."""
    bank_name = request.data.get('bank_name')
    account_holder = request.data.get('account_holder_name')
    account_number = request.data.get('account_number')
    ifsc_code = request.data.get('ifsc_code', '')

    if not bank_name:
        return Response({'error': 'bank_name is required'}, status=400)

    bank = Bank.objects.filter(bank_name=bank_name).first()
    if not bank:
        return Response({'error': f'Bank {bank_name} not found'}, status=404)

    folder_name = f"{bank_name} - {account_holder} - {account_number}"
    company_name = _get_company_name(request)

    drive_result = drive_service.create_bank_folder_structure(folder_name, company_name=company_name)

    if not drive_result['success']:
        return Response({'error': drive_result['message']}, status=500)

    # Save bank account record in DB
    company = request.user.company
    bank_account, created = BankAccount.objects.get_or_create(
        company=company,
        bank=bank,
        account_number=account_number,
        defaults={
            'account_holder_name': account_holder,
            'ifsc_code': ifsc_code,
            'bank_folder_id': drive_result.get('bank_folder_id'),
            'statement_folder_id': drive_result.get('statement_folder_id'),
            'drive_link': drive_result.get('bank_folder_link'),
        }
    )

    return Response({
        'success': True,
        'message': f'Google Drive folders created for {folder_name}',
        'bank_account': BankAccountSerializer(bank_account).data,
        'drive_folders': {
            'total_folders': drive_result.get('total_folders_created', 0)
        }
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_drive_folder_async(request):
    """
    Async version of folder creation.
    Existing sync endpoint remains unchanged.
    """
    bank_name = request.data.get('bank_name')
    account_holder = request.data.get('account_holder_name')
    account_number = request.data.get('account_number')

    if not bank_name:
        return Response({'error': 'bank_name is required'}, status=400)

    if not Bank.objects.filter(bank_name=bank_name).exists():
        return Response({'error': f'Bank {bank_name} not found'}, status=404)

    folder_name = f"{bank_name} - {account_holder} - {account_number}"
    company_name = _get_company_name(request)

    task = create_drive_folder_task.delay(folder_name, company_name=company_name)
    return Response(
        {
            'success': True,
            'message': 'Folder creation queued',
            'task_id': task.id,
            'status_url': f"/api/tasks/{task.id}/status/",
        },
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def task_status(request, task_id):
    task_result = AsyncResult(task_id)
    payload = {
        'task_id': task_id,
        'status': task_result.status,
    }

    if task_result.successful():
        payload['result'] = task_result.result
    elif task_result.failed():
        payload['error'] = str(task_result.result)

    return Response(payload, status=status.HTTP_200_OK)




@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_to_drive(request):
    """
    Upload a file directly into the bank's 'Statement' folder.
    (Month-based subfolder routing is disabled — see commented-out
    logic below for the old per-month behavior.)
    """
    try:
        bank_name = request.data.get('bank_name')
        statement_folder_id = request.data.get('statement_folder_id')  # ← changed from bank_folder_id
        uploaded_file = request.FILES.get('file')

        if not bank_name or not statement_folder_id or not uploaded_file:
            return Response(
                {'error': 'bank_name, statement_folder_id, and file are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        allowed_types = {
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
            'application/pdf': 'pdf',
            'image/jpeg': 'jpg',
            'image/png': 'png',
        }

        mime_type = uploaded_file.content_type
        if mime_type not in allowed_types:
            return Response(
                {'error': f'Unsupported file type: {mime_type}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ------------------------------------------------------------------
        # OLD LOGIC (commented out): detect month/year from filename and
        # upload to a matching month subfolder. Restore this if per-month
        # folders are reintroduced.
        # ------------------------------------------------------------------
        # month, year = detect_month_year_from_filename(uploaded_file.name)
        # if not month:
        #     now = datetime.now()
        #     month, year = now.month, now.year
        # month_name = calendar.month_name[month]
        # target_folder_name = f"{year}-{month:02d}-{month_name}"
        # month_folder_id = drive_service.folder_exists(target_folder_name, bank_folder_id)
        # if not month_folder_id:
        #     month_folder_id = drive_service.create_folder(target_folder_name, bank_folder_id)
        # ------------------------------------------------------------------

        # Step: Upload file directly into the Statement folder
        result = drive_service.upload_file(
            file_obj=uploaded_file,
            file_name=uploaded_file.name,
            folder_id=statement_folder_id,
            mime_type=mime_type
        )

        if not result:
            return Response(
                {'error': 'Failed to upload file to Google Drive'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            'success': True,
            'message': 'File uploaded to Statement folder',
            'file': result
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        print(f"❌ Error uploading file: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_to_drive_async(request):
    """
    Async version of upload endpoint.
    Existing sync endpoint remains unchanged.
    """
    bank_name = request.data.get('bank_name')
    statement_folder_id = request.data.get('statement_folder_id')
    uploaded_file = request.FILES.get('file')

    if not bank_name or not statement_folder_id or not uploaded_file:
        return Response(
            {'error': 'bank_name, statement_folder_id, and file are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    allowed_types = {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
        'application/pdf': 'pdf',
        'image/jpeg': 'jpg',
        'image/png': 'png',
    }

    mime_type = uploaded_file.content_type
    if mime_type not in allowed_types:
        return Response(
            {'error': f'Unsupported file type: {mime_type}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    task = upload_to_drive_task.delay(
        uploaded_file.read(),
        uploaded_file.name,
        statement_folder_id,
        mime_type,
    )
    return Response(
        {
            'success': True,
            'message': 'File upload queued',
            'task_id': task.id,
            'status_url': f"/api/tasks/{task.id}/status/",
        },
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.save()
    refresh = RefreshToken.for_user(user)

    return Response({
        'success': True,
        'message': 'Account created successfully',
        'user': {
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name,
            'company': user.company.name,
        },
        'tokens': {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.validated_data['user']
    refresh = RefreshToken.for_user(user)

    return Response({
        'success': True,
        'message': 'Login successful',
        'user': {
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name,
            'company': user.company.name if user.company else None,
        },
        'tokens': {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def logout(request):
    try:
        refresh_token = request.data.get('refresh')
        token = RefreshToken(refresh_token)
        token.blacklist()
        return Response({'success': True, 'message': 'Logged out'}, status=status.HTTP_200_OK)
    except Exception:
        return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)