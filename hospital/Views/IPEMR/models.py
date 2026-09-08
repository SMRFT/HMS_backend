from djongo import models
from django.utils.timezone import now
from ...models import AuditModel


class IPDoctorNotes(AuditModel):
    _id = models.ObjectIdField()

    # Patient & Admission References (Demographics fetched dynamically from Patient & Admission)
    uhid = models.CharField(max_length=50, blank=True, null=True)
    ip_number = models.CharField(max_length=50, blank=True, null=True)

    # Doctor Reference
    doctor_id = models.CharField(max_length=50, blank=True, null=True)
    department = models.CharField(max_length=100, blank=True, null=True)

    # Note Metadata
    note_type = models.CharField(max_length=100, default='Admission Note', blank=True, null=True)
    note_date = models.DateTimeField(default=now)
    is_finalized = models.BooleanField(default=False)

    # 1. Allergies (Drug, Food, Environmental, Severity, Reaction, Notes)
    allergies = models.JSONField(default=dict, blank=True, null=True)

    # 2. Chief Complaints (Array of complaints with duration, severity, description)
    chief_complaints = models.JSONField(default=list, blank=True, null=True)

    # 3. Past History (Medical: HTN, DM, CAD, Asthma etc.; Surgical; Family History)
    past_history = models.JSONField(default=dict, blank=True, null=True)

    # 4. Present Medications (Array of medications: name, dose, freq, route, duration, remarks)
    present_medications = models.JSONField(default=list, blank=True, null=True)

    # 5. Social History (Smoking, Alcohol, Diet, Occupation, Lifestyle habits, Notes)
    social_history = models.JSONField(default=dict, blank=True, null=True)

    # 6. Menstrual History (LMP, Menarche Age, Cycle Regularity, Flow, Dysmenorrhea, Menopause)
    menstrual_history = models.JSONField(default=dict, blank=True, null=True)

    # 7. Vaccination History (COVID-19, TT, Hepatitis B, Influenza, Others, Notes)
    vaccination_history = models.JSONField(default=dict, blank=True, null=True)

    # 8. Obstetrics History (Gravida, Para, Abortions, Living, Ectopic, Delivery Mode, High Risk)
    obstetrics_history = models.JSONField(default=dict, blank=True, null=True)

    # 9. Investigation Done If Any (Lab Tests, Radiology/Imaging, Summaries, Reports)
    investigations_done = models.JSONField(default=dict, blank=True, null=True)

    # 10. Physical Examination (General: Pallor, Icterus, Edema etc.; Vitals; Systemic: CVS, RS, CNS, PA, Local)
    physical_examination = models.JSONField(default=dict, blank=True, null=True)

    # 11. Provisional Diagnosis (Primary, Secondary, ICD-10/11, Differential Diagnosis)
    provisional_diagnosis = models.JSONField(default=dict, blank=True, null=True)

    # 12. Plan of Care (Treatment Orders, Investigations Advised, Diet Orders, Nursing/Monitoring, Consults)
    plan_of_care = models.JSONField(default=dict, blank=True, null=True)

    # Additional Clinical Notes / Summary text
    additional_notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-note_date']

    def __str__(self):
        return f"IP Doctor Note | {self.ip_number} (Doctor: {self.doctor_id})"


class IPNursingNotes(AuditModel):
    _id = models.ObjectIdField()

    # Patient & Admission References
    uhid = models.CharField(max_length=50, blank=True, null=True)
    ip_number = models.CharField(max_length=50, blank=True, null=True)

    # Nurse Identification
    nurse_id = models.CharField(max_length=50, blank=True, null=True)
    shift = models.CharField(max_length=50, default='Morning', blank=True, null=True) # Morning, Evening, Night
    note_date = models.DateTimeField(default=now)
    is_finalized = models.BooleanField(default=False)

    # 1. Inpatient Vital Signs
    vitals = models.JSONField(default=dict, blank=True, null=True)

    # 2. Pain Scale & Assessment (0 to 10 scale)
    pain_score = models.IntegerField(default=0, blank=True, null=True) # 0 to 10
    pain_severity = models.CharField(max_length=50, default='No Pain', blank=True, null=True)
    pain_location = models.CharField(max_length=255, blank=True, null=True)
    pain_characteristics = models.CharField(max_length=255, blank=True, null=True)

    # 3. Intake & Output Balance Charting
    intake_output = models.JSONField(default=dict, blank=True, null=True)

    # 4. Nursing Physical & Systems Assessment (Consciousness, GCS, Skin, Cannula site, Fall risk, etc.)
    nursing_assessment = models.JSONField(default=dict, blank=True, null=True)

    # 5. Nursing Interventions & Care Given
    nursing_interventions = models.JSONField(default=dict, blank=True, null=True)

    # 6. General Nursing Remarks / Shift Handover Notes
    handover_notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-note_date']

    def __str__(self):
        return f"IP Nursing Note | {self.ip_number} - Pain: {self.pain_score}/10 (Nurse: {self.nurse_id})"
