import * as Notifications from 'expo-notifications';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  FlatList,
  Linking,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import CardNotifications from './modules/card-notifications';

// 결제 알림을 읽을 카드사 앱. 실제 패키지명은 기기에서 `adb shell pm list packages | grep card` 로 확인한다.
const CARD_APPS = [
  'com.android.shell', // 데모: `adb shell cmd notification post` 로 띄운 가짜 카드 알림
  'com.shcard.smartpay', // 신한 SOL페이
  'com.kbcard.cxh.appcard', // KB Pay
  'com.hyundaicard.appcard', // 현대카드
  'kr.co.samsungcard.mpocket', // 삼성카드
];
// 에뮬레이터에서 PC 의 localhost. 실기기는 같은 Wi-Fi 의 PC IP (예: http://192.168.0.12:8000)
const DEFAULT_SERVER = 'http://10.0.2.2:8000';

const CYCLE_LABELS = { monthly: '월', yearly: '연' };
const CONFIDENCE_LABELS = { high: '높음', medium: '중간', low: '낮음' };
const CANCEL_LABELS = { web: '해지하기', google_play: 'Google Play에서 해지', app_store: 'App Store에서 해지' };

const won = (n) => `${n.toLocaleString('ko-KR')}원`;

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

async function api(config, path, options = {}) {
  const response = await fetch(`${config.serverUrl}/api${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${config.token}`, 'Content-Type': 'application/json', ...options.headers },
  });
  const body = await response.json();
  if (!response.ok) throw Object.assign(new Error(body.detail ?? '요청 실패'), { status: response.status });
  return body;
}

export default function App() {
  const [config, setConfig] = useState(() => {
    const saved = CardNotifications.getConfig();
    return saved.serverUrl && saved.token ? saved : null;
  });

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      {config ? (
        <Home config={config} onReset={() => setConfig(null)} />
      ) : (
        <Setup
          onDone={(next) => {
            CardNotifications.configure(next.serverUrl, next.token, CARD_APPS);
            setConfig(next);
          }}
        />
      )}
    </View>
  );
}

function Setup({ onDone }) {
  const [serverUrl, setServerUrl] = useState(DEFAULT_SERVER);
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);

  async function connect() {
    const next = { serverUrl: serverUrl.trim().replace(/\/+$/, ''), token: token.trim() };
    setChecking(true);
    setError('');
    try {
      await api(next, '/subscriptions/').catch((e) => {
        if (e.status !== 404) throw e; // 404 = 아직 결제 내역 없음. 연결은 정상
      });
      onDone(next);
    } catch (e) {
      setError(e.status === 401 ? '토큰이 올바르지 않아요' : `서버에 연결할 수 없어요 (${e.message})`);
    } finally {
      setChecking(false);
    }
  }

  return (
    <View style={styles.setup}>
      <Text style={styles.title}>돈구마</Text>
      <Text style={styles.muted}>카드 결제 알림을 자동으로 모아 구독을 찾아드려요.</Text>
      <Text style={styles.label}>서버 주소</Text>
      <TextInput style={styles.input} value={serverUrl} onChangeText={setServerUrl} autoCapitalize="none"
                 keyboardType="url" />
      <Text style={styles.label}>앱 토큰</Text>
      <TextInput style={styles.input} value={token} onChangeText={setToken} autoCapitalize="none"
                 placeholder="manage.py issue_token phone --scope app" />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button title={checking ? '연결 확인 중…' : '연결하기'} onPress={connect} disabled={checking || !token.trim()} />
    </View>
  );
}

function Home({ config, onReset }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [granted, setGranted] = useState(CardNotifications.isPermissionGranted());

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      setResult(await api(config, '/subscriptions/'));
      setError('');
    } catch (e) {
      if (e.status === 404) setResult({ subscriptions: [], monthly_total: 0, transactions: 0 });
      else setError(e.message);
    } finally {
      setRefreshing(false);
    }
  }, [config]);

  useEffect(() => {
    load();
    Notifications.setNotificationChannelAsync('charges', {
      name: '새 결제',
      importance: Notifications.AndroidImportance.HIGH,
    }).then(() => Notifications.requestPermissionsAsync());

    // 알림 접근 허용 화면에서 돌아오면 권한을 다시 확인하고 밀린 알림을 보낸다
    const appState = AppState.addEventListener('change', (state) => {
      if (state !== 'active') return;
      setGranted(CardNotifications.isPermissionGranted());
      CardNotifications.flush();
      load();
    });
    const charges = CardNotifications.addListener('onCharge', ({ body }) => {
      const { charge, subscription } = JSON.parse(body);
      Notifications.scheduleNotificationAsync({
        content: subscription
          ? { title: `구독 결제: ${subscription.service}`, body: `${won(charge.amount)} · 다음 결제 ${subscription.next_payment_date}` }
          : { title: '새 결제 수집', body: `${charge.merchant} ${won(charge.amount)}` },
        trigger: null,
      });
      load();
    });
    return () => {
      appState.remove();
      charges.remove();
    };
  }, [load]);

  async function confirm(sub, service) {
    try {
      setResult(await api(config, '/merchant-aliases/', {
        method: 'POST',
        body: JSON.stringify({ merchant: sub.merchant, amount: sub.amount, service }),
      }));
    } catch (e) {
      setError(e.message);
    }
  }

  const header = (
    <View>
      <View style={styles.header}>
        <Text style={styles.title}>돈구마</Text>
        <Pressable onPress={onReset} hitSlop={12}>
          <Text style={styles.link}>연결 설정</Text>
        </Pressable>
      </View>
      {!granted && (
        <View style={[styles.card, styles.notice]}>
          <Text style={styles.noticeTitle}>결제 알림 접근을 허용해 주세요</Text>
          <Text style={styles.muted}>
            카드사 앱의 결제 알림만 읽어 구독을 찾아요. 다른 앱 알림은 읽지 않고, 카드번호는 저장하지 않아요.
          </Text>
          <Button title="알림 접근 허용하러 가기" onPress={() => CardNotifications.openPermissionSettings()} />
        </View>
      )}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {result && (
        <View style={styles.card}>
          <Text style={styles.muted}>월 구독 합계</Text>
          <Text style={styles.total}>{won(result.monthly_total)}</Text>
          <Text style={styles.muted}>
            구독 {result.subscriptions.length}건 · 결제 {result.transactions}건 분석
          </Text>
        </View>
      )}
    </View>
  );

  if (!result && !error) return <ActivityIndicator style={styles.loading} />;

  return (
    <FlatList
      contentContainerStyle={styles.list}
      data={result?.subscriptions ?? []}
      keyExtractor={(s) => `${s.merchant}-${s.amount}`}
      ListHeaderComponent={header}
      ListEmptyComponent={
        result && <Text style={[styles.muted, styles.empty]}>아직 찾은 구독이 없어요. 결제 알림이 오면 자동으로 모아요.</Text>
      }
      renderItem={({ item }) => <Subscription sub={item} onConfirm={(service) => confirm(item, service)} />}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}
    />
  );
}

function Subscription({ sub, onConfirm }) {
  const confirmed = sub.confidence === 'high';
  const notes = [
    sub.service !== sub.merchant && `명세서 표기: ${sub.merchant}`,
    sub.price_history.length > 1 && '금액 변경됨',
  ].filter(Boolean);

  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.flex}>
          <Text style={styles.name}>{sub.service}</Text>
          {notes.length > 0 && <Text style={styles.small}>{notes.join(' · ')}</Text>}
        </View>
        <Text style={styles.amount}>
          {won(sub.amount)}
          <Text style={styles.small}>/{CYCLE_LABELS[sub.cycle]}</Text>
        </Text>
      </View>
      <View style={styles.row}>
        <Text style={styles.small}>다음 결제 {sub.next_payment_date}</Text>
        <Text style={[styles.small, styles[sub.confidence]]}>신뢰도 {CONFIDENCE_LABELS[sub.confidence]}</Text>
      </View>
      {confirmed ? (
        sub.cancel && (
          <Button variant="secondary" title={CANCEL_LABELS[sub.cancel.via]} onPress={() => Linking.openURL(sub.cancel.url)} />
        )
      ) : sub.candidates.length > 0 ? (
        <View>
          <Text style={styles.small}>어떤 서비스인가요? 확인하면 해지 방법을 알려드려요.</Text>
          <View style={styles.chips}>
            {sub.candidates.map((c) => (
              <Pressable key={c.service} style={styles.chip} onPress={() => onConfirm(c.service)}>
                <Text style={styles.chipText}>{c.service}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      ) : (
        <Text style={styles.small}>어떤 서비스인지 찾지 못했어요.</Text>
      )}
    </View>
  );
}

function Button({ title, onPress, disabled, variant = 'primary' }) {
  const secondary = variant === 'secondary';
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        styles.button,
        secondary && styles.buttonSecondary,
        (disabled || pressed) && styles.buttonDim,
      ]}
    >
      <Text style={[styles.buttonText, secondary && styles.buttonTextSecondary]}>{title}</Text>
    </Pressable>
  );
}

const colors = {
  bg: '#f6f7f9',
  surface: '#ffffff',
  text: '#1b1d21',
  muted: '#646b76',
  border: '#e3e6ea',
  accent: '#2f6fed',
  error: '#c62828',
  high: '#1f7a4d',
  medium: '#a15c00',
  low: '#8a8f98',
};

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  setup: { padding: 24, paddingTop: 64, gap: 8 },
  list: { padding: 16, paddingTop: 48, gap: 12 },
  loading: { marginTop: 120 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  title: { fontSize: 26, fontWeight: '700', color: colors.text },
  label: { marginTop: 12, fontWeight: '600', color: colors.text },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    padding: 12,
    backgroundColor: colors.surface,
    color: colors.text,
  },
  muted: { color: colors.muted },
  small: { color: colors.muted, fontSize: 13 },
  error: { color: colors.error, marginVertical: 8 },
  link: { color: colors.accent, fontWeight: '600' },
  empty: { textAlign: 'center', marginTop: 24 },
  card: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 16,
    gap: 10,
    marginTop: 12,
  },
  notice: { borderColor: colors.accent },
  noticeTitle: { fontWeight: '700', color: colors.text },
  total: { fontSize: 32, fontWeight: '700', color: colors.text },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  flex: { flex: 1 },
  name: { fontSize: 16, fontWeight: '600', color: colors.text },
  amount: { fontSize: 16, fontWeight: '600', color: colors.text },
  high: { color: colors.high, fontWeight: '600' },
  medium: { color: colors.medium, fontWeight: '600' },
  low: { color: colors.low, fontWeight: '600' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  chip: { borderWidth: 1, borderColor: colors.accent, borderRadius: 8, paddingVertical: 6, paddingHorizontal: 14 },
  chipText: { color: colors.accent },
  button: { backgroundColor: colors.accent, borderRadius: 8, paddingVertical: 12, alignItems: 'center', marginTop: 8 },
  buttonSecondary: { backgroundColor: 'transparent', borderWidth: 1, borderColor: colors.border },
  buttonDim: { opacity: 0.5 },
  buttonText: { color: '#fff', fontWeight: '600' },
  buttonTextSecondary: { color: colors.accent },
});
