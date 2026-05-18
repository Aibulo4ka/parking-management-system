/**
 * Telegram link service
 * Привязка/отвязка Telegram-аккаунта и опрос статуса.
 */
import apiClient from './api';

const telegramService = {
  /** GET /api/telegram/status → { linked, telegram_chat_id, bot_username } */
  getStatus: async () => {
    const response = await apiClient.get('/api/telegram/status');
    return response.data;
  },

  /** POST /api/telegram/link-token → { token, deep_link, expires_at, ttl_seconds } */
  createLinkToken: async () => {
    const response = await apiClient.post('/api/telegram/link-token');
    return response.data;
  },

  /** DELETE /api/telegram/link → { message } */
  unlink: async () => {
    const response = await apiClient.delete('/api/telegram/link');
    return response.data;
  },
};

export default telegramService;
