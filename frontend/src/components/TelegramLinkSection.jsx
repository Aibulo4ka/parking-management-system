import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Link,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import TelegramIcon from '@mui/icons-material/Telegram';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import LinkOffIcon from '@mui/icons-material/LinkOff';
import telegramService from '../services/telegramService';

const STATUS_POLL_INTERVAL_MS = 3000;
const STATUS_POLL_DURATION_MS = 60_000;

const TelegramLinkSection = () => {
  const [status, setStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [pendingLink, setPendingLink] = useState(null);

  const pollTimerRef = useRef(null);
  const pollStopTimerRef = useRef(null);

  const loadStatus = useCallback(async () => {
    try {
      const data = await telegramService.getStatus();
      setStatus(data);
      return data;
    } catch (err) {
      setError(err.message || 'Не удалось получить статус Telegram');
      return null;
    }
  }, []);

  useEffect(() => {
    (async () => {
      setStatusLoading(true);
      await loadStatus();
      setStatusLoading(false);
    })();
  }, [loadStatus]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (pollStopTimerRef.current) {
      clearTimeout(pollStopTimerRef.current);
      pollStopTimerRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollTimerRef.current = setInterval(async () => {
      const data = await loadStatus();
      if (data?.linked) {
        stopPolling();
        setPendingLink(null);
        setSuccess('Telegram успешно привязан');
      }
    }, STATUS_POLL_INTERVAL_MS);
    pollStopTimerRef.current = setTimeout(stopPolling, STATUS_POLL_DURATION_MS);
  }, [loadStatus, stopPolling]);

  useEffect(() => stopPolling, [stopPolling]);

  const handleConnect = async () => {
    setError('');
    setSuccess('');
    setActionLoading(true);
    try {
      const data = await telegramService.createLinkToken();
      setPendingLink(data);
      window.open(data.deep_link, '_blank', 'noopener,noreferrer');
      startPolling();
    } catch (err) {
      setError(err.message || 'Не удалось сгенерировать токен');
    } finally {
      setActionLoading(false);
    }
  };

  const handleUnlink = async () => {
    setError('');
    setSuccess('');
    setActionLoading(true);
    try {
      await telegramService.unlink();
      setPendingLink(null);
      stopPolling();
      await loadStatus();
      setSuccess('Telegram отвязан');
    } catch (err) {
      setError(err.message || 'Не удалось отвязать Telegram');
    } finally {
      setActionLoading(false);
    }
  };

  const linked = Boolean(status?.linked);

  return (
    <Paper elevation={2} sx={{ p: 3, mb: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <TelegramIcon color="primary" />
        <Typography variant="h5">Telegram-уведомления</Typography>
        {!statusLoading && (
          <Chip
            label={linked ? 'Привязан' : 'Не привязан'}
            color={linked ? 'success' : 'default'}
            size="small"
            sx={{ ml: 1 }}
          />
        )}
      </Box>
      <Divider sx={{ mb: 3 }} />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}
      {success && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess('')}>
          {success}
        </Alert>
      )}

      {statusLoading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
          <CircularProgress size={28} />
        </Box>
      ) : linked ? (
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            Уведомления о бронированиях, въезде/выезде и оплатах приходят в Telegram.
            {status?.telegram_chat_id && (
              <>
                {' '}Привязан chat_id <code>{status.telegram_chat_id}</code>.
              </>
            )}
          </Typography>
          <Box>
            <Button
              variant="outlined"
              color="error"
              startIcon={<LinkOffIcon />}
              onClick={handleUnlink}
              disabled={actionLoading}
            >
              {actionLoading ? 'Отвязка…' : 'Отвязать Telegram'}
            </Button>
          </Box>
        </Stack>
      ) : (
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            Подключите бот <b>@{status?.bot_username || 'parkovkatorbot'}</b>, чтобы
            получать уведомления о бронированиях и парковочных сессиях прямо в Telegram.
          </Typography>
          <Box>
            <Button
              variant="contained"
              color="primary"
              startIcon={<TelegramIcon />}
              onClick={handleConnect}
              disabled={actionLoading}
            >
              {actionLoading ? 'Подготовка ссылки…' : 'Подключить Telegram'}
            </Button>
          </Box>
          {pendingLink && (
            <Alert severity="info" icon={<OpenInNewIcon fontSize="inherit" />}>
              <Typography variant="body2" sx={{ mb: 0.5 }}>
                Если Telegram не открылся автоматически —{' '}
                <Link href={pendingLink.deep_link} target="_blank" rel="noopener noreferrer">
                  откройте ссылку вручную
                </Link>
                .
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Ссылка действует {Math.round((pendingLink.ttl_seconds || 0) / 60)} мин.
                После подтверждения в боте этот раздел обновится автоматически.
              </Typography>
            </Alert>
          )}
        </Stack>
      )}
    </Paper>
  );
};

export default TelegramLinkSection;
