from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "risk_tolerance",
        "max_daily_loss_pct",
        "max_position_size_pct",
        "updated_at",
    )
    list_filter = ("risk_tolerance",)
    search_fields = ("user__username", "user__email")
