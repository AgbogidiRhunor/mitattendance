from django import forms
from django.utils import timezone

from .models import AttendanceAuditLog, MeetingSession

DT_FORMAT = "%Y-%m-%dT%H:%M"


class SessionForm(forms.ModelForm):
    class Meta:
        model = MeetingSession
        fields = ["title", "meeting_date", "opens_at", "closes_at"]
        labels = {"opens_at": "Opens at", "closes_at": "Closes at"}
        widgets = {
            "meeting_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "opens_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT_FORMAT),
            "closes_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT_FORMAT),
        }

    def clean(self):
        cleaned = super().clean()
        opens, closes = cleaned.get("opens_at"), cleaned.get("closes_at")
        if opens and closes:
            if closes <= opens:
                self.add_error("closes_at", "The closing time must be after the opening time.")
            elif closes <= timezone.now():
                self.add_error("closes_at", "The closing time must be in the future.")
        return cleaned


class CorrectionForm(forms.Form):
    action = forms.ChoiceField(choices=AttendanceAuditLog.Action.choices, widget=forms.HiddenInput)
    reason = forms.CharField(min_length=5, max_length=1000, label="Reason for correction",
                             widget=forms.Textarea(attrs={"rows": 3}))


class DateRangeForm(forms.Form):
    date_from = forms.DateField(required=False, label="From", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, label="To", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("date_from") and cleaned.get("date_to") and cleaned["date_from"] > cleaned["date_to"]:
            raise forms.ValidationError("The start date must not be after the end date.")
        return cleaned

    def apply(self, qs):
        if not self.is_valid():
            return qs
        if self.cleaned_data.get("date_from"):
            qs = qs.filter(meeting_date__gte=self.cleaned_data["date_from"])
        if self.cleaned_data.get("date_to"):
            qs = qs.filter(meeting_date__lte=self.cleaned_data["date_to"])
        return qs
