from django.contrib import admin
from .models import FilePermission

@admin.register(FilePermission)
class FilePermissionAdmin(admin.ModelAdmin):
    list_display = ('user', 'student_file', 'granted_by', 'granted_at')
    list_filter = ('granted_at',)
