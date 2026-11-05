import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; message?: string; resetKey?: unknown };
type State = { failed: boolean; resetKey: unknown };

/** Keeps one broken part of a page from blanking the rest (M1.3): a panel that throws shows a short message in its
 *  place and everything around it stays (React itself reports the error in the browser's console). When `resetKey`
 *  changes (the replay moved on, another run was chosen) the part is tried again, in the same render: the state
 *  remembers the key it was last shown with. The one class component React still requires. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, resetKey: this.props.resetKey };

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return Object.is(props.resetKey, state.resetKey) ? null : { failed: false, resetKey: props.resetKey };
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <p className="notice bad" role="alert">
        {this.props.message ?? "This part could not be shown; the rest of the page is fine. Reloading the page usually helps."}
      </p>
    );
  }
}
