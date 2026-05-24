from django import forms
from .models import StudentFile, Student


class ExcelUploadForm(forms.Form):
    class_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g., B.Tech Computer Science',
        })
    )
    division = forms.ChoiceField(
        choices=[('', '-- Select --'), ('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')],
        widget=forms.Select(attrs={'class': 'form-input'})
    )
    year = forms.ChoiceField(
        choices=[
            ('', '-- Select --'),
            ('FY', 'First Year'),
            ('SY', 'Second Year'),
            ('TY', 'Third Year'),
            ('Final', 'Final Year'),
        ],
        widget=forms.Select(attrs={'class': 'form-input'})
    )
    academic_year = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g., 2024-2025',
        })
    )
    excel_file = forms.FileField(
        widget=forms.FileInput(attrs={
            'class': 'form-input',
            'accept': '.xlsx,.xls',
        })
    )


class StudentEditForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = [
            'full_name', 'roll_no', 'prn', 'abc_id', 'phone', 'email',
            'parent_name', 'parent_phone', 'birthdate', 'gender',
            'address', 'permanent_address', 'photo',
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-input'}),
            'roll_no': forms.TextInput(attrs={'class': 'form-input'}),
            'prn': forms.TextInput(attrs={'class': 'form-input'}),
            'abc_id': forms.TextInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'parent_name': forms.TextInput(attrs={'class': 'form-input'}),
            'parent_phone': forms.TextInput(attrs={'class': 'form-input'}),
            'birthdate': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'gender': forms.Select(attrs={'class': 'form-input'}),
            'address': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'permanent_address': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'photo': forms.FileInput(attrs={'class': 'form-input'}),
        }
