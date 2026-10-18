from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Address, User


@admin.register(User)
class WeekendStoreUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Rol de la tienda", {"fields": ("role", "phone")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Rol de la tienda", {"fields": ("role", "phone")}),
    )
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
    list_filter = UserAdmin.list_filter + ("role",)


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "city", "country", "is_default")
    list_filter = ("country", "is_default")
    search_fields = ("full_name", "user__username", "city")
