 
import openpyxl
from io import BytesIO
from django.http import HttpResponse


def parse_excel(file):
    """Parse uploaded Excel file and return list of student dicts."""
    try:
        wb = openpyxl.load_workbook(file, read_only=True)
        ws = wb.active

        students = []
        errors = []
        headers = []

        for row_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
            if row_idx < 3:
                continue  # Skip title and instructions rows
            if row_idx == 3:
                # Header row - map column names
                headers = [str(cell).strip().lower() if cell else '' for cell in row]
                continue
            # Skip empty rows
            if not any(row):
                continue
            # Map row data to dict using headers
            row_data = {}
            for col_idx, value in enumerate(row):
                if col_idx < len(headers):
                    row_data[headers[col_idx]] = str(value).strip() if value else ''

            # Extract student data - flexible header matching
            student = {
                'roll_no': row_data.get('roll_no', row_data.get('roll no', row_data.get('rollno', row_data.get('roll', '')))),
                'prn': row_data.get('prn', row_data.get('prn no', row_data.get('prn_no', ''))),
                'full_name': row_data.get('full_name', row_data.get('name', row_data.get('full name', row_data.get('student name', '')))),
                'phone': row_data.get('phone', row_data.get('phone no', row_data.get('mobile', row_data.get('phone_no', '')))),
                'email': row_data.get('email', row_data.get('email id', row_data.get('email_id', ''))),
                'parent_name': row_data.get('parent_name', row_data.get('parent name', row_data.get('guardian name', ''))),
                'parent_phone': row_data.get('parent_phone', row_data.get('parent phone', row_data.get('parent mobile', ''))),
                'address': row_data.get('address', ''),
            }

            # Validate required fields
            if not student['roll_no']:
                errors.append(f'Row {row_idx}: Missing roll number')
                continue
            if not student['full_name']:
                errors.append(f'Row {row_idx}: Missing student name')
                continue

            # Generate PRN if missing
            if not student['prn']:
                student['prn'] = f'PRN-{student["roll_no"]}'

            students.append(student)

        wb.close()
        return students, errors

    except Exception as e:
        return [], [f'Error reading Excel file: {str(e)}']


def export_students_excel(students, file_name='students'):
    """Export student list as Excel file."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Students'

    # Headers
    headers = ['Roll No', 'PRN', 'Full Name', 'Phone', 'Email',
               'Parent Name', 'Parent Phone', 'Address', 'Class',
               'Division', 'Year', 'Status']
    ws.append(headers)

    # Bold headers
    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)

    # Data
    for student in students:
        ws.append([
            student.roll_no,
            student.prn,
            student.full_name,
            student.phone,
            student.email,
            student.parent_name,
            student.parent_phone,
            student.address,
            student.class_name,
            student.division,
            student.year,
            student.get_status_display(),
        ])

    # Auto-width columns
    for column_cells in ws.columns:
        length = max(len(str(cell.value or '')) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 40)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{file_name}.xlsx"'
    wb.save(response)
    return response
