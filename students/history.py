"""
Edit history logging for student records.
Captures field-level changes before save.
"""
from .models import StudentEditLog
from .field_registry import CORE_FIELDS


def log_student_changes(student, form, user):
    """
    Compare form cleaned_data to student's current values and log each change.
    Must be called BEFORE form.save().
    """
    logs = []

    for field_name in form.changed_data:
        if field_name == 'photo':
            # Log photo change but don't store binary data
            logs.append(StudentEditLog(
                student=student,
                field_name='photo',
                field_label='Photo',
                old_value='(previous photo)' if student.photo else '(no photo)',
                new_value='(new photo uploaded)',
                changed_by=user,
            ))
            continue

        old_val = str(getattr(student, field_name, '') or '')
        new_val = str(form.cleaned_data.get(field_name, '') or '')

        if old_val != new_val:
            # Get display label
            if field_name in CORE_FIELDS:
                label = CORE_FIELDS[field_name]['label']
            else:
                label = field_name.replace('_', ' ').title()

            logs.append(StudentEditLog(
                student=student,
                field_name=field_name,
                field_label=label,
                old_value=old_val,
                new_value=new_val,
                changed_by=user,
            ))

    if logs:
        StudentEditLog.objects.bulk_create(logs)

    return logs


def log_extra_data_changes(student, old_extra, new_extra, user):
    """Log changes to extra_data JSONField."""
    logs = []
    all_keys = set(list(old_extra.keys()) + list(new_extra.keys()))

    for key in all_keys:
        old_val = str(old_extra.get(key, '') or '')
        new_val = str(new_extra.get(key, '') or '')
        if old_val != new_val:
            logs.append(StudentEditLog(
                student=student,
                field_name=f'extra:{key}',
                field_label=key.replace('_', ' ').title(),
                old_value=old_val,
                new_value=new_val,
                changed_by=user,
            ))

    if logs:
        StudentEditLog.objects.bulk_create(logs)

    return logs
