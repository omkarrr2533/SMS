from django.contrib import admin
from .models import StudentFile, Student

@admin.register(StudentFile)
class StudentFileAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'class_name', 'division', 'year', 'total_students', 'upload_date')
    list_filter = ('year', 'division', 'class_name')
    search_fields = ('file_name', 'class_name')

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('roll_no', 'prn', 'full_name', 'class_name', 'division', 'status')
    list_filter = ('status', 'class_name', 'division', 'year')
    search_fields = ('full_name', 'roll_no', 'prn')
