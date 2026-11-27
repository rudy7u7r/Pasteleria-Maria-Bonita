from django import forms
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm

LARGO_MINIMO_PASSWORD = 8


class RecuperarPasswordForm(PasswordResetForm):
    email = forms.EmailField(
        label="Correo electrónico",
        max_length=254,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'autocomplete': 'email',
            'placeholder': 'correo@ejemplo.com',
        }),
    )


class NuevaPasswordForm(SetPasswordForm):
    """Mismas reglas que el registro: mínimo 8 caracteres y ambas contraseñas iguales."""

    error_messages = {
        'password_mismatch': "Las contraseñas ingresadas no coinciden.",
    }

    new_password1 = forms.CharField(
        label="Nueva contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
            'minlength': LARGO_MINIMO_PASSWORD,
            'placeholder': f'Mínimo {LARGO_MINIMO_PASSWORD} caracteres',
        }),
    )
    new_password2 = forms.CharField(
        label="Confirmar nueva contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
            'minlength': LARGO_MINIMO_PASSWORD,
            'placeholder': 'Repita la contraseña',
        }),
    )

    def clean_new_password2(self):
        p1 = self.cleaned_data.get('new_password1') or ''
        p2 = self.cleaned_data.get('new_password2') or ''
        if len(p1) < LARGO_MINIMO_PASSWORD:
            raise forms.ValidationError(f"La contraseña debe tener al menos {LARGO_MINIMO_PASSWORD} caracteres.")
        if p1 != p2:
            raise forms.ValidationError(self.error_messages['password_mismatch'])
        return p2
