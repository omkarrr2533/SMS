import os
import json
import zipfile
import tempfile
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, Http404, JsonResponse
from django.conf import settings
from django.db.models import Q, Count
from django.utils import timezone
from datetime import datetime

from accounts.decorators import admin_required, role_required
from accounts.utils import log_action
from .models import StudentFile, Student, ColumnMapping, StudentEditLog
from .forms import ExcelUploadForm, StudentEditForm
from .utils import (
    parse_excel, parse_excel_headers, parse_excel_with_mapping,
    export_students_excel, export_dynamic_excel, export_dynamic_pdf,
)
from .field_registry import CORE_FIELDS, FIELD_CATEGORIES, auto_suggest_mapping, get_core_field_choices


# ============================================================
# UPLOAD FLOW: upload_excel → map_columns → import_preview
# ============================================================

@login_required
@admin_required
def upload_excel(request):
    """Step 1: Upload Excel file — parse headers and redirect to mapping."""
    form = ExcelUploadForm()

    if request.method == 'POST':
        form = ExcelUploadForm(request.POST, request.FILES)

        if form.is_valid():
            class_name = form.cleaned_data['class_name']
            division = form.cleaned_data['division']
            year = form.cleaned_data['year']
            academic_year = form.cleaned_data['academic_year']
            excel_file = form.cleaned_data['excel_file']

            # Validate file extension
            ext = os.path.splitext(excel_file.name)[1].lower()
            if ext not in settings.ALLOWED_EXCEL_EXTENSIONS:
                messages.error(request, 'Only .xlsx and .xls files are allowed.')
                return render(request, 'students/upload_excel.html', {'form': form})

            # Validate file size
            if excel_file.size > settings.MAX_UPLOAD_SIZE:
                messages.error(request, 'File size exceeds 10MB limit.')
                return render(request, 'students/upload_excel.html', {'form': form})

            # Check for duplicate
            if StudentFile.objects.filter(
                class_name=class_name,
                division=division,
                year=year,
                academic_year=academic_year,
                is_active=True
            ).exists():
                messages.error(request, 'A file for this class/division/year/academic year already exists.')
                return render(request, 'students/upload_excel.html', {'form': form})

            # Parse headers and preview
            headers, preview_rows, error = parse_excel_headers(excel_file)

            if error:
                messages.error(request, error)
                return render(request, 'students/upload_excel.html', {'form': form})

            # Save file temporarily
            temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads')
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, f'upload_{request.user.pk}_{int(timezone.now().timestamp())}{ext}')
            with open(temp_path, 'wb') as f:
                excel_file.seek(0)
                for chunk in excel_file.chunks():
                    f.write(chunk)

            # Store upload data in session
            request.session['upload_data'] = {
                'temp_path': temp_path,
                'original_name': excel_file.name,
                'headers': headers,
                'preview_rows': preview_rows,
                'class_name': class_name,
                'division': division,
                'year': year,
                'academic_year': academic_year,
            }

            return redirect('map_columns')

    return render(request, 'students/upload_excel.html', {'form': form})


@login_required
@admin_required
def map_columns(request):
    """Step 2: Map Excel columns to system fields."""
    upload_data = request.session.get('upload_data')
    if not upload_data:
        messages.error(request, 'No file uploaded. Please upload a file first.')
        return redirect('upload_excel')

    headers = upload_data['headers']
    saved_mappings = ColumnMapping.objects.filter(created_by=request.user)[:10]

    if request.method == 'POST':
        # Check if loading a saved mapping
        load_mapping_id = request.POST.get('load_mapping')
        if load_mapping_id:
            try:
                saved = ColumnMapping.objects.get(pk=load_mapping_id, created_by=request.user)
                saved.use_count += 1
                saved.save()
                mapping = saved.mapping
            except ColumnMapping.DoesNotExist:
                mapping = {}
        else:
            # Build mapping from form
            mapping = {}
            for header in headers:
                target = request.POST.get(f'map_{header}', 'skip')
                mapping[header] = target

            # Save mapping if requested
            save_name = request.POST.get('save_mapping_name', '').strip()
            if save_name:
                ColumnMapping.objects.create(
                    name=save_name,
                    mapping=mapping,
                    created_by=request.user,
                )

        upload_data['mapping'] = mapping
        request.session['upload_data'] = upload_data
        request.session.modified = True
        return redirect('import_preview')

    # Auto-suggest mapping
    suggestions = auto_suggest_mapping(headers)
    field_choices = get_core_field_choices()

    return render(request, 'students/map_columns.html', {
        'headers': headers,
        'preview_rows': upload_data['preview_rows'],
        'suggestions': suggestions,
        'field_choices': field_choices,
        'saved_mappings': saved_mappings,
        'form_data': upload_data,
    })


@login_required
@admin_required
def import_preview(request):
    """Step 3: Preview mapped data and confirm import."""
    upload_data = request.session.get('upload_data')
    if not upload_data or 'mapping' not in upload_data:
        messages.error(request, 'No mapping found. Please map columns first.')
        return redirect('upload_excel')

    temp_path = upload_data['temp_path']
    mapping = upload_data['mapping']

    if request.method == 'POST':
        # CONFIRM: Actually create StudentFile + Students
        try:
            with open(temp_path, 'rb') as f:
                students_data, errors, total = parse_excel_with_mapping(f, mapping)
        except FileNotFoundError:
            messages.error(request, 'Upload file expired. Please upload again.')
            return redirect('upload_excel')

        class_name = upload_data['class_name']
        division = upload_data['division']
        year = upload_data['year']
        academic_year = upload_data['academic_year']
        file_name = f"{year}_{division}_{class_name}_{academic_year}"

        # Re-read file for saving
        from django.core.files import File
        with open(temp_path, 'rb') as f:
            django_file = File(f, name=upload_data['original_name'])

            student_file = StudentFile.objects.create(
                file_name=file_name,
                class_name=class_name,
                division=division,
                year=year,
                academic_year=academic_year,
                excel_file=django_file,
                uploaded_by=request.user,
                total_students=len(students_data),
                column_headers=upload_data['headers'],
                column_mapping=mapping,
            )

        # Create Students
        student_objects = []
        for data in students_data:
            core = data['core']
            extra = data['extra']

            # Parse birthdate
            birthdate_value = None
            if core.get('birthdate'):
                for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%d %b %Y', '%d %B %Y']:
                    try:
                        birthdate_value = datetime.strptime(core['birthdate'], fmt).date()
                        break
                    except (ValueError, TypeError):
                        continue

            student_objects.append(Student(
                file=student_file,
                roll_no=core.get('roll_no', ''),
                prn=core.get('prn', ''),
                abc_id=core.get('abc_id', ''),
                full_name=core.get('full_name', ''),
                phone=core.get('phone', ''),
                email=core.get('email', ''),
                parent_name=core.get('parent_name', ''),
                parent_phone=core.get('parent_phone', ''),
                birthdate=birthdate_value,
                gender=core.get('gender', '').strip().lower() if core.get('gender') else '',
                address=core.get('address', ''),
                permanent_address=core.get('permanent_address', ''),
                class_name=class_name,
                division=division,
                year=year,
                extra_data=extra,
            ))

        Student.objects.bulk_create(student_objects)

        log_action(request.user, 'file_upload', request,
                   f'Uploaded {file_name} with {len(students_data)} students')

        # Cleanup
        try:
            os.remove(temp_path)
        except OSError:
            pass
        if 'upload_data' in request.session:
            del request.session['upload_data']

        success_msg = f'File uploaded successfully! {len(students_data)} students imported.'
        if errors:
            success_msg += f' ({len(errors)} rows skipped)'
        messages.success(request, success_msg)
        return redirect('file_list')

    # GET: Show preview
    try:
        with open(temp_path, 'rb') as f:
            students_data, errors, total = parse_excel_with_mapping(f, mapping)
    except FileNotFoundError:
        messages.error(request, 'Upload file expired. Please upload again.')
        return redirect('upload_excel')

    return render(request, 'students/import_preview.html', {
        'students_data': students_data[:10],
        'errors': errors[:10],
        'total_valid': len(students_data),
        'total_errors': len(errors),
        'total_rows': total,
        'mapping': mapping,
        'form_data': upload_data,
    })


# ============================================================
# FILE & STUDENT VIEWS
# ============================================================

@login_required
def file_list(request):
    """List all student files."""
    user = request.user
    search = request.GET.get('search', '')
    year_filter = request.GET.get('year', '')

    if user.role == 'admin' or user.role == 'hod':
        files = StudentFile.objects.filter(is_active=True)
    elif user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        allowed_file_ids = FilePermission.objects.filter(
            user=user
        ).values_list('student_file_id', flat=True)
        files = StudentFile.objects.filter(id__in=allowed_file_ids, is_active=True)
    else:
        files = StudentFile.objects.none()

    if search:
        files = files.filter(
            Q(file_name__icontains=search) |
            Q(class_name__icontains=search) |
            Q(division__icontains=search)
        )

    if year_filter:
        files = files.filter(year=year_filter)

    years = StudentFile.objects.filter(is_active=True).values_list(
        'year', flat=True
    ).distinct().order_by('year')

    paginator = Paginator(files, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'students/file_list.html', {
        'page_obj': page_obj,
        'search': search,
        'years': years,
        'selected_year': year_filter,
    })


@login_required
def student_list(request, file_id):
    """List students in a file with advanced filters."""
    student_file = get_object_or_404(StudentFile, pk=file_id, is_active=True)

    # Permission check
    user = request.user
    if user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        if not FilePermission.objects.filter(user=user, student_file=student_file).exists():
            messages.error(request, 'You do not have permission to view this file.')
            return redirect('file_list')

    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    gender_filter = request.GET.get('gender', '')

    students = student_file.students.all()

    if search:
        students = students.filter(
            Q(full_name__icontains=search) |
            Q(roll_no__icontains=search) |
            Q(prn__icontains=search)
        )

    if status_filter:
        students = students.filter(status=status_filter)

    if gender_filter:
        students = students.filter(gender=gender_filter)

    # Collect extra data keys for this file's students
    extra_keys = set()
    for s in student_file.students.all():
        if s.extra_data:
            extra_keys.update(s.extra_data.keys())

    paginator = Paginator(students, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Available columns for export modal
    export_columns = list(CORE_FIELDS.keys()) + [f'extra:{k}' for k in sorted(extra_keys)]

    return render(request, 'students/student_list.html', {
        'student_file': student_file,
        'page_obj': page_obj,
        'search': search,
        'status_filter': status_filter,
        'gender_filter': gender_filter,
        'extra_keys': sorted(extra_keys),
        'export_columns': export_columns,
        'core_fields': CORE_FIELDS,
    })


@login_required
def student_profile(request, pk):
    """View full student profile with dynamic fields."""
    student = get_object_or_404(Student, pk=pk)

    # Permission check
    user = request.user
    if user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        if not FilePermission.objects.filter(user=user, student_file=student.file).exists():
            messages.error(request, 'You do not have permission to view this student.')
            return redirect('file_list')

    field_sections = student.get_all_fields()
    edit_logs = student.edit_logs.select_related('changed_by')[:20]

    return render(request, 'students/student_profile.html', {
        'student': student,
        'field_sections': field_sections,
        'edit_logs': edit_logs,
    })


@login_required
@admin_required
def student_edit(request, pk):
    """Edit student record with change tracking."""
    student = get_object_or_404(Student, pk=pk)

    if request.method == 'POST':
        form = StudentEditForm(request.POST, request.FILES, instance=student)
        if form.is_valid():
            # Log changes BEFORE saving
            from .history import log_student_changes, log_extra_data_changes
            log_student_changes(student, form, request.user)

            # Handle extra_data edits
            old_extra = dict(student.extra_data) if student.extra_data else {}
            new_extra = {}
            for key in (student.extra_data or {}).keys():
                new_val = request.POST.get(f'extra_{key}', '').strip()
                new_extra[key] = new_val

            if old_extra != new_extra:
                log_extra_data_changes(student, old_extra, new_extra, request.user)
                student.extra_data = new_extra

            form.save()

            # Save extra_data separately if changed
            if old_extra != new_extra:
                Student.objects.filter(pk=student.pk).update(extra_data=new_extra)

            log_action(request.user, 'student_edit', request,
                       f'Edited student: {student.full_name}')
            messages.success(request, f'Student "{student.full_name}" updated successfully!')
            return redirect('student_profile', pk=student.pk)
    else:
        form = StudentEditForm(instance=student)

    return render(request, 'students/student_edit.html', {
        'form': form,
        'student': student,
        'extra_data': student.extra_data or {},
    })


@login_required
@admin_required
def revert_edit(request, pk, log_id):
    """Revert a single field change."""
    student = get_object_or_404(Student, pk=pk)
    edit_log = get_object_or_404(StudentEditLog, pk=log_id, student=student)

    if request.method == 'POST':
        field_name = edit_log.field_name

        if field_name.startswith('extra:'):
            key = field_name[6:]
            extra = dict(student.extra_data or {})
            extra[key] = edit_log.old_value
            student.extra_data = extra
            student.save()
        elif hasattr(student, field_name):
            setattr(student, field_name, edit_log.old_value)
            student.save()

        edit_log.is_reverted = True
        edit_log.save()

        # Log the revert
        StudentEditLog.objects.create(
            student=student,
            field_name=field_name,
            field_label=edit_log.field_label,
            old_value=edit_log.new_value,
            new_value=edit_log.old_value,
            changed_by=request.user,
        )

        messages.success(request, f'Reverted "{edit_log.field_label}" to previous value.')

    return redirect('student_profile', pk=pk)


@login_required
@admin_required
def student_delete(request, pk):
    """Delete a student."""
    student = get_object_or_404(Student, pk=pk)
    file_id = student.file_id

    if request.method == 'POST':
        student_name = student.full_name
        student.delete()

        student_file = StudentFile.objects.get(pk=file_id)
        student_file.total_students = student_file.students.count()
        student_file.save()

        log_action(request.user, 'student_delete', request,
                   f'Deleted student: {student_name}')
        messages.success(request, f'Student "{student_name}" deleted successfully!')

    return redirect('student_list', file_id=file_id)


@login_required
@admin_required
def file_delete(request, file_id):
    """Delete a student file and all its students."""
    student_file = get_object_or_404(StudentFile, pk=file_id, is_active=True)

    if request.method == 'POST':
        file_name = student_file.file_name
        student_file.students.all().delete()
        student_file.is_active = False
        student_file.save()

        log_action(request.user, 'file_delete', request,
                   f'Deleted file: {file_name}')
        messages.success(request, f'File "{file_name}" deleted successfully!')

    return redirect('file_list')


@login_required
def file_download(request, file_id):
    """Download students as Excel."""
    student_file = get_object_or_404(StudentFile, pk=file_id, is_active=True)

    user = request.user
    if user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        if not FilePermission.objects.filter(user=user, student_file=student_file).exists():
            messages.error(request, 'You do not have permission to download this file.')
            return redirect('file_list')

    students = student_file.students.all()
    return export_students_excel(students, student_file.file_name)


@login_required
def my_assigned_files(request):
    """Show files assigned to teacher/guardian."""
    from permissions_app.models import FilePermission

    assigned = FilePermission.objects.filter(
        user=request.user
    ).select_related('student_file')

    file_ids = assigned.values_list('student_file_id', flat=True)
    files = StudentFile.objects.filter(id__in=file_ids, is_active=True)

    paginator = Paginator(files, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'students/file_list.html', {
        'page_obj': page_obj,
        'search': '',
        'years': [],
        'selected_year': '',
    })


@login_required
def student_pdf(request, pk):
    """Generate PDF for student profile."""
    student = get_object_or_404(Student, pk=pk)

    user = request.user
    if user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        if not FilePermission.objects.filter(user=user, student_file=student.file).exists():
            messages.error(request, 'You do not have permission to download this student profile.')
            return redirect('file_list')

    try:
        from xhtml2pdf import pisa
        from io import BytesIO
        from django.template.loader import render_to_string

        field_sections = student.get_all_fields()
        html_string = render_to_string('students/student_pdf.html', {
            'student': student,
            'field_sections': field_sections,
        })

        result = BytesIO()
        pdf = pisa.CreatePDF(BytesIO(html_string.encode('utf-8')), dest=result)

        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{student.full_name}_Profile.pdf"'
            return response
        else:
            messages.error(request, 'Error generating PDF.')
            return redirect('student_profile', pk=pk)

    except ImportError:
        messages.error(request, 'PDF generation is not available. Please install xhtml2pdf.')
        return redirect('student_profile', pk=pk)


# ============================================================
# SMART EXPORT
# ============================================================

@login_required
def smart_export(request, file_id):
    """Export students with selected columns and format."""
    student_file = get_object_or_404(StudentFile, pk=file_id, is_active=True)

    user = request.user
    if user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        if not FilePermission.objects.filter(user=user, student_file=student_file).exists():
            messages.error(request, 'Permission denied.')
            return redirect('file_list')

    if request.method == 'POST':
        columns = request.POST.getlist('columns')
        format_type = request.POST.get('format', 'excel')

        if not columns:
            messages.error(request, 'Please select at least one column.')
            return redirect('student_list', file_id=file_id)

        students = student_file.students.all()

        if format_type == 'pdf':
            return export_dynamic_pdf(students, columns, student_file.file_name)
        else:
            return export_dynamic_excel(students, columns, student_file.file_name)

    return redirect('student_list', file_id=file_id)


# ============================================================
# GLOBAL SEARCH
# ============================================================

@login_required
def search_api(request):
    """JSON API for navbar search dropdown."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    results = []
    user = request.user

    # Students (respect permissions)
    student_qs = Student.objects.filter(
        Q(full_name__icontains=q) | Q(roll_no__icontains=q) | Q(prn__icontains=q),
        file__is_active=True,
    )
    if user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        allowed_files = FilePermission.objects.filter(user=user).values_list('student_file_id', flat=True)
        student_qs = student_qs.filter(file_id__in=allowed_files)

    for s in student_qs[:5]:
        results.append({
            'type': 'student',
            'icon': 'ti-user',
            'title': s.full_name,
            'subtitle': f'Roll: {s.roll_no} | PRN: {s.prn}',
            'url': f'/students/{s.pk}/',
        })

    # Files
    file_qs = StudentFile.objects.filter(
        Q(file_name__icontains=q) | Q(class_name__icontains=q),
        is_active=True,
    )
    if user.role in ('teacher', 'guardian'):
        file_qs = file_qs.filter(id__in=allowed_files)

    for f in file_qs[:3]:
        results.append({
            'type': 'file',
            'icon': 'ti-file',
            'title': f.file_name,
            'subtitle': f'{f.total_students} students',
            'url': f'/files/{f.pk}/',
        })

    # Staff (admin only)
    if user.role == 'admin':
        from accounts.models import User
        staff_qs = User.objects.filter(
            Q(full_name__icontains=q) | Q(email__icontains=q),
            is_active=True,
        ).exclude(pk=user.pk)

        for u in staff_qs[:3]:
            results.append({
                'type': 'staff',
                'icon': 'ti-users',
                'title': u.full_name,
                'subtitle': u.get_role_display(),
                'url': f'/teachers/{u.pk}/' if u.role == 'teacher' else f'/guardians/{u.pk}/' if u.role == 'guardian' else f'/hods/{u.pk}/',
            })

    # Announcements
    from announcements.models import Announcement
    ann_qs = Announcement.objects.filter(
        Q(title__icontains=q) | Q(content__icontains=q),
        is_active=True,
    )
    for a in ann_qs[:3]:
        results.append({
            'type': 'announcement',
            'icon': 'ti-speakerphone',
            'title': a.title,
            'subtitle': a.get_category_display(),
            'url': f'/announcements/{a.pk}/',
        })

    return JsonResponse({'results': results})


@login_required
def global_search(request):
    """Full search results page."""
    q = request.GET.get('q', '').strip()
    results = {'students': [], 'files': [], 'staff': [], 'announcements': []}

    if len(q) >= 2:
        user = request.user

        student_qs = Student.objects.filter(
            Q(full_name__icontains=q) | Q(roll_no__icontains=q) | Q(prn__icontains=q),
            file__is_active=True,
        )
        if user.role in ('teacher', 'guardian'):
            from permissions_app.models import FilePermission
            allowed_files = FilePermission.objects.filter(user=user).values_list('student_file_id', flat=True)
            student_qs = student_qs.filter(file_id__in=allowed_files)
        results['students'] = student_qs[:20]

        file_qs = StudentFile.objects.filter(
            Q(file_name__icontains=q) | Q(class_name__icontains=q),
            is_active=True,
        )
        if user.role in ('teacher', 'guardian'):
            file_qs = file_qs.filter(id__in=allowed_files)
        results['files'] = file_qs[:10]

        if user.role == 'admin':
            from accounts.models import User
            results['staff'] = User.objects.filter(
                Q(full_name__icontains=q) | Q(email__icontains=q),
                is_active=True,
            )[:10]

        from announcements.models import Announcement
        results['announcements'] = Announcement.objects.filter(
            Q(title__icontains=q), is_active=True,
        )[:10]

    return render(request, 'students/global_search.html', {
        'query': q,
        'results': results,
    })


# ============================================================
# PER-FILE ANALYTICS
# ============================================================

@login_required
def file_analytics(request, file_id):
    """Per-file analytics: completion rates, edit requests, activity."""
    student_file = get_object_or_404(StudentFile, pk=file_id, is_active=True)

    user = request.user
    if user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        if not FilePermission.objects.filter(user=user, student_file=student_file).exists():
            messages.error(request, 'Permission denied.')
            return redirect('file_list')

    students = student_file.students.all()
    total = students.count()

    # Completion rates
    phone_filled = students.exclude(phone='').count()
    email_filled = students.exclude(email='').count()
    photo_filled = students.exclude(photo='').exclude(photo=None).count()
    parent_filled = students.exclude(parent_phone='').count()

    completion = {
        'Phone': round(phone_filled / total * 100) if total else 0,
        'Email': round(email_filled / total * 100) if total else 0,
        'Photo': round(photo_filled / total * 100) if total else 0,
        'Parent Contact': round(parent_filled / total * 100) if total else 0,
    }

    # Status breakdown
    status_data = dict(students.values_list('status').annotate(count=Count('id')).values_list('status', 'count'))

    # Edit request breakdown
    from notifications.models import Notification
    edit_requests = Notification.objects.filter(student_file=student_file)
    field_breakdown = list(
        edit_requests.values('field_to_edit')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    return render(request, 'students/file_analytics.html', {
        'student_file': student_file,
        'total_students': total,
        'completion': json.dumps(completion),
        'status_data': json.dumps(status_data),
        'field_breakdown': json.dumps(field_breakdown),
        'phone_filled': phone_filled,
        'email_filled': email_filled,
        'photo_filled': photo_filled,
        'parent_filled': parent_filled,
        'edit_request_count': edit_requests.count(),
        'pending_requests': edit_requests.filter(status='pending').count(),
    })


# ============================================================
# BULK PHOTO IMPORT
# ============================================================

@login_required
@admin_required
def bulk_photo_upload(request, file_id):
    """Upload ZIP of photos to auto-match by roll number."""
    student_file = get_object_or_404(StudentFile, pk=file_id, is_active=True)

    if request.method == 'POST':
        zip_file = request.FILES.get('photo_zip')
        if not zip_file:
            messages.error(request, 'Please select a ZIP file.')
            return redirect('bulk_photo_upload', file_id=file_id)

        if not zip_file.name.endswith('.zip'):
            messages.error(request, 'Please upload a .zip file.')
            return redirect('bulk_photo_upload', file_id=file_id)

        try:
            zf = zipfile.ZipFile(zip_file)
        except zipfile.BadZipFile:
            messages.error(request, 'Invalid ZIP file.')
            return redirect('bulk_photo_upload', file_id=file_id)

        matched = []
        unmatched = []
        valid_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

        for name in zf.namelist():
            if name.endswith('/'):
                continue
            basename = os.path.basename(name)
            fname, ext = os.path.splitext(basename)
            if ext.lower() not in valid_extensions:
                continue

            # Try matching roll_no from filename
            roll_no = fname.strip()
            try:
                student = student_file.students.get(roll_no=roll_no)
                matched.append({'filename': basename, 'roll_no': roll_no, 'student': student.full_name, 'student_id': student.pk})
            except Student.DoesNotExist:
                unmatched.append({'filename': basename, 'roll_no': roll_no})

        # Store ZIP in temp for confirmation
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads')
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, f'photos_{request.user.pk}_{int(timezone.now().timestamp())}.zip')
        with open(temp_path, 'wb') as f:
            zip_file.seek(0)
            for chunk in zip_file.chunks():
                f.write(chunk)

        request.session['photo_upload'] = {
            'temp_path': temp_path,
            'file_id': file_id,
            'matched': matched,
            'unmatched': unmatched,
        }

        return render(request, 'students/photo_match_report.html', {
            'student_file': student_file,
            'matched': matched,
            'unmatched': unmatched,
        })

    return render(request, 'students/bulk_photo_upload.html', {
        'student_file': student_file,
    })


@login_required
@admin_required
def confirm_photo_upload(request, file_id):
    """Confirm and save matched photos."""
    if request.method != 'POST':
        return redirect('bulk_photo_upload', file_id=file_id)

    photo_data = request.session.get('photo_upload')
    if not photo_data or photo_data['file_id'] != file_id:
        messages.error(request, 'No photo upload to confirm.')
        return redirect('bulk_photo_upload', file_id=file_id)

    student_file = get_object_or_404(StudentFile, pk=file_id, is_active=True)

    try:
        zf = zipfile.ZipFile(photo_data['temp_path'])
    except (FileNotFoundError, zipfile.BadZipFile):
        messages.error(request, 'Photo file expired. Please upload again.')
        return redirect('bulk_photo_upload', file_id=file_id)

    saved_count = 0
    for match in photo_data['matched']:
        try:
            student = Student.objects.get(pk=match['student_id'], file=student_file)
        except Student.DoesNotExist:
            continue

        # Find the file in the ZIP
        for name in zf.namelist():
            basename = os.path.basename(name)
            fname, ext = os.path.splitext(basename)
            if fname.strip() == match['roll_no']:
                from django.core.files.base import ContentFile
                photo_data_bytes = zf.read(name)
                student.photo.save(
                    f"{student.roll_no}{ext}",
                    ContentFile(photo_data_bytes),
                    save=True,
                )
                saved_count += 1
                break

    zf.close()

    # Cleanup
    try:
        os.remove(photo_data['temp_path'])
    except OSError:
        pass
    if 'photo_upload' in request.session:
        del request.session['photo_upload']

    log_action(request.user, 'file_upload', request,
               f'Bulk uploaded {saved_count} photos for {student_file.file_name}')
    messages.success(request, f'{saved_count} photos saved successfully!')
    return redirect('student_list', file_id=file_id)


# ============================================================
# STUDENT ID CARD / QR CODE
# ============================================================

@login_required
def student_id_card(request, pk):
    """Generate printable ID card with QR code."""
    student = get_object_or_404(Student, pk=pk)

    user = request.user
    if user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        if not FilePermission.objects.filter(user=user, student_file=student.file).exists():
            messages.error(request, 'Permission denied.')
            return redirect('file_list')

    try:
        import qrcode
        import base64
        from io import BytesIO as QRBytesIO

        profile_url = request.build_absolute_uri(f'/students/{pk}/')
        qr = qrcode.make(profile_url)
        buffer = QRBytesIO()
        qr.save(buffer, format='PNG')
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()
    except ImportError:
        qr_base64 = None

    try:
        from xhtml2pdf import pisa
        from io import BytesIO
        from django.template.loader import render_to_string

        html_string = render_to_string('students/id_card_pdf.html', {
            'student': student,
            'qr_base64': qr_base64,
        })

        result = BytesIO()
        pdf = pisa.CreatePDF(BytesIO(html_string.encode('utf-8')), dest=result)

        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{student.full_name}_ID_Card.pdf"'
            return response

    except ImportError:
        pass

    messages.error(request, 'PDF generation not available.')
    return redirect('student_profile', pk=pk)


@login_required
def bulk_id_cards(request, file_id):
    """Generate ID cards for all students in a file."""
    student_file = get_object_or_404(StudentFile, pk=file_id, is_active=True)

    user = request.user
    if user.role in ('teacher', 'guardian'):
        from permissions_app.models import FilePermission
        if not FilePermission.objects.filter(user=user, student_file=student_file).exists():
            messages.error(request, 'Permission denied.')
            return redirect('file_list')

    students = student_file.students.all()

    try:
        import qrcode
        import base64
        from io import BytesIO as QRBytesIO

        student_cards = []
        for student in students:
            profile_url = request.build_absolute_uri(f'/students/{student.pk}/')
            qr = qrcode.make(profile_url)
            buffer = QRBytesIO()
            qr.save(buffer, format='PNG')
            qr_b64 = base64.b64encode(buffer.getvalue()).decode()
            student_cards.append({'student': student, 'qr_base64': qr_b64})
    except ImportError:
        student_cards = [{'student': s, 'qr_base64': None} for s in students]

    try:
        from xhtml2pdf import pisa
        from io import BytesIO
        from django.template.loader import render_to_string

        html_string = render_to_string('students/bulk_id_cards_pdf.html', {
            'student_cards': student_cards,
            'student_file': student_file,
        })

        result = BytesIO()
        pdf = pisa.CreatePDF(BytesIO(html_string.encode('utf-8')), dest=result)

        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{student_file.file_name}_ID_Cards.pdf"'
            return response

    except ImportError:
        pass

    messages.error(request, 'PDF generation not available.')
    return redirect('student_list', file_id=file_id)
