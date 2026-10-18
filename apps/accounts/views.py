from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import AddressForm, ProfileForm, RegisterForm
from .models import Address


class WeekendStoreLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


class WeekendStoreLogoutView(LogoutView):
    next_page = "catalog:home"


class RegisterView(CreateView):
    form_class = RegisterForm
    template_name = "accounts/register.html"
    success_url = reverse_lazy("catalog:home")

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(self.request, "¡Bienvenida/o a The Weekend Store!")
        return response


@login_required
def profile(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Perfil actualizado correctamente.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    addresses = request.user.addresses.all()
    return render(
        request,
        "accounts/profile.html",
        {"form": form, "addresses": addresses},
    )


@login_required
def address_create(request):
    if request.method == "POST":
        form = AddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            address.save()
            messages.success(request, "Dirección agregada.")
            return redirect("accounts:profile")
    else:
        form = AddressForm()
    return render(request, "accounts/address_form.html", {"form": form, "is_new": True})


@login_required
def address_update(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method == "POST":
        form = AddressForm(request.POST, instance=address)
        if form.is_valid():
            form.save()
            messages.success(request, "Dirección actualizada.")
            return redirect("accounts:profile")
    else:
        form = AddressForm(instance=address)
    return render(request, "accounts/address_form.html", {"form": form, "is_new": False})


@login_required
def address_delete(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method == "POST":
        address.delete()
        messages.success(request, "Dirección eliminada.")
        return redirect("accounts:profile")
    return render(request, "accounts/address_confirm_delete.html", {"address": address})
