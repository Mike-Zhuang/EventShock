import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  api,
  ApiError,
  AUTH_SESSION_EXPIRED_EVENT,
  setCsrfToken,
} from '../api/client';
import type {
  AuthUser,
  LegalAcceptanceStatus,
  LegalConsentInput,
  UserPreferences,
  UserPreferencesInput,
  VerificationCodeReceipt,
  VerificationPurpose,
} from '../api/types';
import { synchronizeGuidedHandoffOwner } from '../guided-handoff';
import type { Language } from '../i18n';

export type AuthenticationState = 'checking' | 'authenticated' | 'unauthenticated' | 'error';

interface AuthContextValue {
  state: AuthenticationState;
  user?: AuthUser;
  legalAcceptance?: LegalAcceptanceStatus;
  preferences?: UserPreferences;
  error?: string;
  refreshSession: () => Promise<void>;
  login: (email: string, password: string, language: Language) => Promise<void>;
  register: (
    email: string,
    password: string,
    verificationCode: string,
    consent: LegalConsentInput,
  ) => Promise<void>;
  acceptLegalDocuments: (consent: LegalConsentInput) => Promise<void>;
  completeOnboarding: (input: UserPreferencesInput) => Promise<void>;
  requestVerificationCode: (
    email: string,
    purpose: VerificationPurpose,
    language: Language,
  ) => Promise<VerificationCodeReceipt>;
  resetPassword: (
    email: string,
    password: string,
    verificationCode: string,
    language: Language,
  ) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthenticationState>('checking');
  const [user, setUser] = useState<AuthUser>();
  const [legalAcceptance, setLegalAcceptance] = useState<LegalAcceptanceStatus>();
  const [preferences, setPreferences] = useState<UserPreferences>();
  const [error, setError] = useState<string>();

  const applyAuthenticatedSession = useCallback((session: Awaited<ReturnType<typeof api.getAuthSession>>) => {
    if (!session.authenticated || !session.user) {
      synchronizeGuidedHandoffOwner();
      setCsrfToken(undefined);
      setUser(undefined);
      setLegalAcceptance(undefined);
      setPreferences(undefined);
      setState('unauthenticated');
      return;
    }
    synchronizeGuidedHandoffOwner(session.user.id);
    setCsrfToken(session.csrfToken);
    setUser(session.user);
    setLegalAcceptance(session.legalAcceptance);
    setPreferences(session.preferences);
    setState('authenticated');
  }, []);

  const refreshSession = useCallback(async () => {
    setState('checking');
    setError(undefined);
    try {
      const session = await api.getAuthSession();
      applyAuthenticatedSession(session);
      const currentHash = window.location.hash;
      if (
        session.authenticated
        && session.preferences
        && !session.preferences.onboardingRequired
        && (currentHash === '' || currentHash === '#' || currentHash === '#/')
      ) {
        window.history.replaceState(
          null,
          '',
          '#/guided',
        );
      }
    } catch (sessionError) {
      synchronizeGuidedHandoffOwner();
      setCsrfToken(undefined);
      setUser(undefined);
      setLegalAcceptance(undefined);
      setPreferences(undefined);
      if (sessionError instanceof ApiError && sessionError.status === 401) {
        setState('unauthenticated');
        return;
      }
      setState('error');
      setError(errorMessage(sessionError));
    }
  }, [applyAuthenticatedSession]);

  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

  useEffect(() => {
    const expireSession = () => {
      synchronizeGuidedHandoffOwner();
      setCsrfToken(undefined);
      setUser(undefined);
      setLegalAcceptance(undefined);
      setPreferences(undefined);
      setError(undefined);
      setState('unauthenticated');
    };
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, expireSession);
    return () => window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, expireSession);
  }, []);

  const login = useCallback(async (email: string, password: string, language: Language) => {
    setError(undefined);
    const session = await api.login({ email, password, language });
    applyAuthenticatedSession(session);
    if (session.preferences && !session.preferences.onboardingRequired) {
      window.history.replaceState(
        null,
        '',
        '#/guided',
      );
    }
  }, [applyAuthenticatedSession]);

  const register = useCallback(async (
    email: string,
    password: string,
    verificationCode: string,
    consent: LegalConsentInput,
  ) => {
    setError(undefined);
    applyAuthenticatedSession(await api.register({
      email,
      password,
      verificationCode,
      ...consent,
    }));
  }, [applyAuthenticatedSession]);

  const acceptLegalDocuments = useCallback(async (consent: LegalConsentInput) => {
    setError(undefined);
    setLegalAcceptance(await api.acceptLegalDocuments(consent));
  }, []);

  const completeOnboarding = useCallback(async (input: UserPreferencesInput) => {
    setError(undefined);
    setPreferences(await api.saveUserPreferences(input));
  }, []);

  const requestVerificationCode = useCallback((
    email: string,
    purpose: VerificationPurpose,
    language: Language,
  ) => api.requestVerificationCode({ email, purpose, language }), []);

  const resetPassword = useCallback(async (
    email: string,
    password: string,
    verificationCode: string,
    language: Language,
  ) => {
    await api.resetPassword({ email, password, verificationCode, language });
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (logoutError) {
      if (logoutError instanceof ApiError && logoutError.status === 403) {
        // 页面长时间打开后 CSRF 可能过期；先从 HttpOnly 会话恢复新令牌，再只重试一次。
        applyAuthenticatedSession(await api.getAuthSession());
        await api.logout();
      } else {
        setError(errorMessage(logoutError));
        throw logoutError;
      }
    }
    try {
      synchronizeGuidedHandoffOwner();
      setCsrfToken(undefined);
      setUser(undefined);
      setLegalAcceptance(undefined);
      setPreferences(undefined);
      setError(undefined);
      setState('unauthenticated');
      window.history.replaceState(null, '', '#/cases');
    } catch (stateError) {
      setError(errorMessage(stateError));
      throw stateError;
    }
  }, [applyAuthenticatedSession]);

  const value = useMemo<AuthContextValue>(() => ({
    state,
    user,
    legalAcceptance,
    preferences,
    error,
    refreshSession,
    login,
    register,
    acceptLegalDocuments,
    completeOnboarding,
    requestVerificationCode,
    resetPassword,
    logout,
  }), [
    error,
    acceptLegalDocuments,
    completeOnboarding,
    legalAcceptance,
    login,
    logout,
    refreshSession,
    register,
    requestVerificationCode,
    resetPassword,
    state,
    user,
    preferences,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider.');
  return context;
}
