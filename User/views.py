"""Operator UI for the current user's trading profile (Phase 9 U6)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import UserProfileForm
from .models import UserProfile


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    form = UserProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Trading profile saved.")
        return redirect("user:profile")
    return render(request, "User/profile_form.html", {"form": form, "profile": profile})
