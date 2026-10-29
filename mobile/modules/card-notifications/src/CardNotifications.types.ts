export type CardNotificationsModuleEvents = {
  /** 서버가 결제 알림을 새 거래로 저장했을 때. body 는 POST /api/notifications/ 응답 JSON 문자열 */
  onCharge: (event: { body: string }) => void;
};
