import { NativeModule, requireNativeModule } from 'expo';

import { CardNotificationsModuleEvents } from './CardNotifications.types';

declare class CardNotificationsModule extends NativeModule<CardNotificationsModuleEvents> {
  isPermissionGranted(): boolean;
  openPermissionSettings(): void;
  /** 서버 주소·앱 토큰·수집할 카드사 앱 패키지명을 저장하고 밀린 알림을 보낸다 */
  configure(serverUrl: string, token: string, cardPackages: string[]): void;
  getConfig(): { serverUrl: string; token: string };
  flush(): void;
  pendingCount(): number;
}

export default requireNativeModule<CardNotificationsModule>('CardNotifications');
