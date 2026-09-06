from django import forms

from .models import UserProfile


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["risk_tolerance", "max_daily_loss_pct", "max_position_size_pct"]
