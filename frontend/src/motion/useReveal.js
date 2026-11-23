import { useEffect } from "react";
import "./reveal.css";

// data-reveal 그룹이 화면 아래 85% 선을 넘으면 data-revealed 를 붙인다.
// key 가 바뀔 때(대시보드 진입, 페이지 전환)마다 새로 그려진 그룹을 다시 찾는다.
export function useReveal(key) {
  useEffect(() => {
    if (key == null) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.dataset.revealed = "";
          observer.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -15% 0px" },
    );
    document
      .querySelectorAll("[data-reveal]:not([data-revealed])")
      .forEach((group) => {
        // 카드 순서대로 등장 지연(--i)을 매긴다. 긴 목록은 12번째부터 함께 나온다.
        [...group.children].forEach((child, i) =>
          child.style.setProperty("--i", Math.min(i, 12)),
        );
        observer.observe(group);
      });
    return () => observer.disconnect();
  }, [key]);
}
