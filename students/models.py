from django.db import models
from django.conf import settings


class StudentFile(models.Model):
    file_name = models.CharField(max_length=255)
    class_name = models.CharField(max_length=100)
    division = models.CharField(max_length=10)
    year = models.CharField(max_length=50)
    academic_year = models.CharField(max_length=20)
    section = models.CharField(max_length=50, blank=True, default='')
    excel_file = models.FileField(upload_to='excel_files/')
    total_students = models.IntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_files'
    )
    upload_date = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    # Dynamic column support
    column_headers = models.JSONField(default=list, blank=True)
    column_mapping = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'student_files'
        ordering = ['-upload_date']
        indexes = [
            models.Index(fields=['class_name']),
            models.Index(fields=['division']),
            models.Index(fields=['year']),
            models.Index(fields=['academic_year']),
        ]

    def __str__(self):
        return self.file_name


class Student(models.Model):
    STATUS_CHOICES = (
        ('normal', 'Normal'),
        ('marked', 'Edit Marked'),
        ('resolved', 'Resolved'),
    )

    GENDER_CHOICES = (
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    )

    file = models.ForeignKey(
        StudentFile,
        on_delete=models.CASCADE,
        related_name='students'
    )
    roll_no = models.CharField(max_length=10)
    prn = models.CharField(max_length=30)
    abc_id = models.CharField(max_length=50, blank=True, default='')
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=15, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    parent_name = models.CharField(max_length=255, blank=True, default='')
    parent_phone = models.CharField(max_length=15, blank=True, default='')
    birthdate = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, default='')
    address = models.TextField(blank=True, default='')
    permanent_address = models.TextField(blank=True, default='')
    photo = models.ImageField(upload_to='student_photos/', blank=True, null=True)
    class_name = models.CharField(max_length=100)
    division = models.CharField(max_length=10)
    year = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='normal')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Dynamic extra data from Excel columns not mapped to core fields
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'students'
        ordering = ['roll_no']
        indexes = [
            models.Index(fields=['file']),
            models.Index(fields=['roll_no']),
            models.Index(fields=['prn']),
            models.Index(fields=['full_name']),
            models.Index(fields=['status']),
        ]
        unique_together = ['file', 'roll_no']

    def __str__(self):
        return f"{self.roll_no} - {self.full_name}"

    @property
    def initials(self):
        if self.full_name:
            parts = self.full_name.strip().split()
            if len(parts) >= 2:
                return (parts[0][0] + parts[-1][0]).upper()
            elif len(parts) == 1:
                return parts[0][0].upper()
        return 'S'

    def get_all_fields(self):
        """Return an ordered dict of all field sections with labels and values."""
        from .field_registry import CORE_FIELDS, FIELD_CATEGORIES
        from collections import OrderedDict

        result = OrderedDict()

        for category_key, category_label in FIELD_CATEGORIES.items():
            fields = []
            if category_key != 'extra':
                for field_name, meta in CORE_FIELDS.items():
                    if meta['category'] == category_key:
                        value = getattr(self, field_name, '') or ''
                        # Special handling for choice fields
                        if field_name == 'gender' and value:
                            value = self.get_gender_display()
                        elif field_name == 'birthdate' and self.birthdate:
                            value = self.birthdate.strftime('%d %b %Y')
                        fields.append({
                            'label': meta['label'],
                            'value': value,
                            'field_name': field_name,
                        })
            else:
                # Extra data from JSONField
                for key, value in (self.extra_data or {}).items():
                    fields.append({
                        'label': key.replace('_', ' ').title(),
                        'value': value or '',
                        'field_name': f'extra:{key}',
                    })

            if fields:
                result[category_label] = fields

        return result


class ColumnMapping(models.Model):
    """Saved column mappings for reuse across uploads."""
    name = models.CharField(max_length=100)
    mapping = models.JSONField()  # {"Excel Header": "core_field_name" or "extra:key"}
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='column_mappings'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    use_count = models.IntegerField(default=0)

    class Meta:
        db_table = 'column_mappings'
        ordering = ['-use_count', '-created_at']

    def __str__(self):
        return f"{self.name} ({self.use_count} uses)"


class StudentEditLog(models.Model):
    """Field-level edit history for student records."""
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='edit_logs'
    )
    field_name = models.CharField(max_length=100)
    field_label = models.CharField(max_length=100)
    old_value = models.TextField(blank=True, default='')
    new_value = models.TextField(blank=True, default='')
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='student_edits'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    is_reverted = models.BooleanField(default=False)

    class Meta:
        db_table = 'student_edit_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['student', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.student.full_name}: {self.field_label} changed by {self.changed_by}"
