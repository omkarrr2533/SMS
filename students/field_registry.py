"""
Core field definitions and categories for the Student model.

CORE_FIELDS maps internal field names to metadata used for:
- Column mapping UI (auto-suggesting Excel header -> field matches)
- Dynamic profile rendering (grouping fields by category)
- Import validation (marking required fields)
- Smart exports (column selection)
"""

CORE_FIELDS = {
    'roll_no': {
        'label': 'Roll Number',
        'type': 'text',
        'required': True,
        'category': 'academic',
        'aliases': ['roll_no', 'roll no', 'rollno', 'roll', 'student roll no', 'sr no', 'sr. no'],
    },
    'prn': {
        'label': 'PRN',
        'type': 'text',
        'required': False,
        'category': 'academic',
        'aliases': ['prn', 'prn no', 'prn_no', 'prn no.', 'prn number'],
    },
    'abc_id': {
        'label': 'ABC ID',
        'type': 'text',
        'required': False,
        'category': 'academic',
        'aliases': ['abc_id', 'abc id', 'abc', 'abc number'],
    },
    'full_name': {
        'label': 'Full Name',
        'type': 'text',
        'required': True,
        'category': 'personal',
        'aliases': ['full_name', 'name', 'full name', 'student name', 'student full name', 'student_name'],
    },
    'phone': {
        'label': 'Phone',
        'type': 'text',
        'required': False,
        'category': 'personal',
        'aliases': ['phone', 'phone no', 'mobile', 'phone_no', 'contact number (student)', 'mobile no', 'contact', 'student phone'],
    },
    'email': {
        'label': 'Email',
        'type': 'email',
        'required': False,
        'category': 'personal',
        'aliases': ['email', 'email id', 'email_id', 'email address', 'student email'],
    },
    'parent_name': {
        'label': 'Parent Name',
        'type': 'text',
        'required': False,
        'category': 'parent',
        'aliases': ['parent_name', 'parent name', 'guardian name', 'father name', "father's name", 'mother name'],
    },
    'parent_phone': {
        'label': 'Parent Phone',
        'type': 'text',
        'required': False,
        'category': 'parent',
        'aliases': ['parent_phone', 'parent phone', 'parent mobile', 'parent contact number (father)', 'guardian phone', 'father phone', 'parent contact'],
    },
    'birthdate': {
        'label': 'Birthdate',
        'type': 'date',
        'required': False,
        'category': 'personal',
        'aliases': ['birthdate', 'birth date', 'dob', 'date of birth', 'birth_date', 'd.o.b'],
    },
    'gender': {
        'label': 'Gender',
        'type': 'choice',
        'required': False,
        'category': 'personal',
        'aliases': ['gender', 'sex'],
    },
    'address': {
        'label': 'Local Address',
        'type': 'textarea',
        'required': False,
        'category': 'personal',
        'aliases': ['address', 'local address', 'current address', 'residential address'],
    },
    'permanent_address': {
        'label': 'Permanent Address',
        'type': 'textarea',
        'required': False,
        'category': 'personal',
        'aliases': ['permanent_address', 'permanent address', 'home address'],
    },
}

FIELD_CATEGORIES = {
    'personal': 'Personal Information',
    'academic': 'Academic Information',
    'parent': 'Parent / Guardian Information',
    'extra': 'Additional Information',
}

# Build a reverse lookup: alias (lowercase) -> core field name
ALIAS_MAP = {}
for field_name, meta in CORE_FIELDS.items():
    for alias in meta['aliases']:
        ALIAS_MAP[alias.lower()] = field_name


def auto_suggest_mapping(excel_headers):
    """
    Given a list of Excel column headers, return a dict mapping
    each header to a suggested core field name or None.
    """
    suggestions = {}
    used_fields = set()

    for header in excel_headers:
        normalized = header.strip().lower()
        if normalized in ALIAS_MAP:
            field = ALIAS_MAP[normalized]
            if field not in used_fields:
                suggestions[header] = field
                used_fields.add(field)
            else:
                suggestions[header] = None
        else:
            suggestions[header] = None

    return suggestions


def get_core_field_choices():
    """Return choices list for the column mapping dropdown."""
    choices = [('skip', '-- Skip this column --')]
    for field_name, meta in CORE_FIELDS.items():
        choices.append((field_name, meta['label']))
    choices.append(('extra', 'Store as extra field'))
    return choices
