import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Container,
  Box,
  Typography,
  Button,
  Paper,
  TextField,
  Alert,
  Grid,
  Divider,
  CircularProgress,
  Chip,
} from '@mui/material';
import { useAuth } from '../context/AuthContext';
import authService from '../services/authService';
import TelegramLinkSection from '../components/TelegramLinkSection';

const ProfilePage = () => {
  const navigate = useNavigate();
  const { user, isAuthenticated, updateUser } = useAuth();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [profileData, setProfileData] = useState({
    first_name: '',
    last_name: '',
    phone: '',
  });

  const [passwordData, setPasswordData] = useState({
    current_password: '',
    new_password: '',
    confirm_password: '',
  });

  useEffect(() => {
    if (!isAuthenticated) {
      navigate('/login');
    } else if (user) {
      setProfileData({
        first_name: user.first_name || '',
        last_name: user.last_name || '',
        phone: user.phone || '',
      });
    }
  }, [isAuthenticated, navigate, user]);

  const handleProfileUpdate = async (e) => {
    e.preventDefault();
    try {
      setLoading(true);
      setError('');
      setSuccess('');

      const updatedUser = await authService.updateProfile(profileData);
      updateUser(updatedUser);
      setSuccess('Профиль успешно обновлен');
    } catch (err) {
      setError(err.message || 'Ошибка обновления профиля');
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    try {
      setLoading(true);
      setError('');
      setSuccess('');

      // Validation
      if (!passwordData.current_password || !passwordData.new_password || !passwordData.confirm_password) {
        setError('Заполните все поля');
        setLoading(false);
        return;
      }

      if (passwordData.new_password !== passwordData.confirm_password) {
        setError('Новые пароли не совпадают');
        setLoading(false);
        return;
      }

      if (passwordData.new_password.length < 6) {
        setError('Новый пароль должен содержать минимум 6 символов');
        setLoading(false);
        return;
      }

      await authService.changePassword({
        current_password: passwordData.current_password,
        new_password: passwordData.new_password,
      });

      setSuccess('Пароль успешно изменен');
      setPasswordData({
        current_password: '',
        new_password: '',
        confirm_password: '',
      });
    } catch (err) {
      setError(err.message || 'Ошибка смены пароля');
    } finally {
      setLoading(false);
    }
  };

  if (!user) {
    return (
      <Container maxWidth="lg">
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '80vh' }}>
          <CircularProgress />
        </Box>
      </Container>
    );
  }

  return (
    <Container maxWidth="md">
      <Box sx={{ mt: 4, mb: 4 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h4">Профиль пользователя</Typography>
          <Button variant="outlined" onClick={() => navigate('/dashboard')}>
            Назад к Dashboard
          </Button>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        {success && (
          <Alert severity="success" sx={{ mb: 3 }} onClose={() => setSuccess('')}>
            {success}
          </Alert>
        )}

        {/* Profile Information */}
        <Paper elevation={2} sx={{ p: 3, mb: 3 }}>
          <Typography variant="h5" sx={{ mb: 2 }}>
            Личная информация
          </Typography>
          <Divider sx={{ mb: 3 }} />

          <form onSubmit={handleProfileUpdate}>
            <Grid container spacing={2}>
              <Grid item xs={12} sm={6}>
                <TextField
                  label="Имя"
                  fullWidth
                  value={profileData.first_name}
                  onChange={(e) => setProfileData({ ...profileData, first_name: e.target.value })}
                  required
                />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField
                  label="Фамилия"
                  fullWidth
                  value={profileData.last_name}
                  onChange={(e) => setProfileData({ ...profileData, last_name: e.target.value })}
                  required
                />
              </Grid>
              <Grid item xs={12}>
                <TextField
                  label="Email"
                  fullWidth
                  value={user.email}
                  disabled
                  helperText="Email нельзя изменить"
                />
              </Grid>
              <Grid item xs={12}>
                <TextField
                  label="Телефон"
                  fullWidth
                  value={profileData.phone}
                  onChange={(e) => setProfileData({ ...profileData, phone: e.target.value })}
                  required
                />
              </Grid>
              <Grid item xs={12}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  <Typography variant="body1" fontWeight="bold">
                    Баланс:
                  </Typography>
                  <Chip
                    label={`${parseFloat(user.balance || 0).toFixed(2)} ₽`}
                    color="success"
                    sx={{ fontWeight: 'bold', fontSize: '1.1rem' }}
                  />
                </Box>
              </Grid>
              <Grid item xs={12}>
                <Button
                  type="submit"
                  variant="contained"
                  color="primary"
                  disabled={loading}
                >
                  {loading ? 'Обновление...' : 'Сохранить изменения'}
                </Button>
              </Grid>
            </Grid>
          </form>
        </Paper>

        {/* Telegram */}
        <TelegramLinkSection />

        {/* Change Password */}
        <Paper elevation={2} sx={{ p: 3 }}>
          <Typography variant="h5" sx={{ mb: 2 }}>
            Смена пароля
          </Typography>
          <Divider sx={{ mb: 3 }} />

          <form onSubmit={handlePasswordChange}>
            <Grid container spacing={2}>
              <Grid item xs={12}>
                <TextField
                  label="Текущий пароль"
                  type="password"
                  fullWidth
                  value={passwordData.current_password}
                  onChange={(e) => setPasswordData({ ...passwordData, current_password: e.target.value })}
                  required
                />
              </Grid>
              <Grid item xs={12}>
                <TextField
                  label="Новый пароль"
                  type="password"
                  fullWidth
                  value={passwordData.new_password}
                  onChange={(e) => setPasswordData({ ...passwordData, new_password: e.target.value })}
                  required
                  helperText="Минимум 6 символов"
                />
              </Grid>
              <Grid item xs={12}>
                <TextField
                  label="Подтвердите новый пароль"
                  type="password"
                  fullWidth
                  value={passwordData.confirm_password}
                  onChange={(e) => setPasswordData({ ...passwordData, confirm_password: e.target.value })}
                  required
                />
              </Grid>
              <Grid item xs={12}>
                <Button
                  type="submit"
                  variant="contained"
                  color="secondary"
                  disabled={loading}
                >
                  {loading ? 'Изменение...' : 'Изменить пароль'}
                </Button>
              </Grid>
            </Grid>
          </form>
        </Paper>
      </Box>
    </Container>
  );
};

export default ProfilePage;
