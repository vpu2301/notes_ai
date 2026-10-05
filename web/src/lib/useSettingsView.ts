import { useSearchParams } from "react-router-dom";

/** Settings section in `?view=`; the first option is the default and leaves the URL clean. */
export function useSettingsView<T extends string>(
  options: readonly { value: T; label: string }[],
): [T, (next: T) => void] {
  const [params, setParams] = useSearchParams();
  const first = options[0]!.value;
  const asked = params.get("view");
  const view = options.find((o) => o.value === asked)?.value ?? first;
  const setView = (next: T) => setParams(next === first ? {} : { view: next }, { replace: true });
  return [view, setView];
}
