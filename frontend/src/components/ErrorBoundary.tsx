import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; message?: string; resetKey?: unknown };
type State = { failed: boolean };

/** Keeps one broken part of a page from blanking the rest (M1.3): a panel that throws shows a short message in its
 *  place and everything around it stays (React itself reports the error in the browser's console). When `resetKey`
 *  changes (the replay moved on, another run was chosen) the part is tried again. The one class component React still
 *  requires. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidUpdate(previous: Props): void {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false });
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
