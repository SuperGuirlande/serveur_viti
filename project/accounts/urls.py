from django.urls import path
from .views import change_password, register, user_login, user_logout, my_account
from django.contrib.auth import views as auth_views


urlpatterns = [
    path('s-inscrire/', register, name='register'),
    path('se-connecter/', user_login, name='login'),
    path('se-deconnecter/', user_logout, name='logout'),
    path('mon-compte/', my_account, name='my_account'),
    path('nouveau-mot-de-passe/', change_password, name="change_password"),

    path('reinitialiser-mot-de-passe/', auth_views.PasswordResetView.as_view(template_name='accounts/password_reset/password_reset_form.html'), name="password_reset"),
    path('reinitialiser-mot-de-passe/envoye/', auth_views.PasswordResetDoneView.as_view(template_name='accounts/password_reset/password_reset_done.html'), name="password_reset_done"),
    path('reinitialiser/<uidb64>/<token>', auth_views.PasswordResetConfirmView.as_view(template_name='accounts/password_reset/password_reset_confirm.html'), name="password_reset_confirm"),
    path('reinitialiser/termine/', auth_views.PasswordResetCompleteView.as_view(template_name='accounts/password_reset/password_reset_complete.html'), name="password_reset_complete"),
]
