import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp } from "@phosphor-icons/react";
import { aiApi, errorText, moveInOrder, type Policy } from "../../lib/ai";

type Props = {
  policy: Policy;
  names: Record<string, string>;
};

/** The order the gateway tries providers in: the first provider with a working key for the tier answers. */
export function ProviderOrder({ policy, names }: Props) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (order: string[]) => aiApi.putPolicy({ order }),
    onSuccess: (data) => queryClient.setQueryData(["ai", "policy"], data),
  });
  const order = policy.order;
  return (
    <div className="order">
      <h3>Order the gateway tries providers</h3>
      <p className="muted small">For each request the first provider in this list with a working key answers; the next one steps in when it fails. Move the provider you trust most to the top.</p>
      <ol className="list order-list" aria-label="Provider order">
        {order.map((id, i) => (
          <li key={id} className="list-row static">
            <span>
              <span className="order-num">{i + 1}.</span> {names[id] ?? id}
            </span>
            <span className="key-actions">
              <button type="button" className="icon-btn" aria-label={`Move ${names[id] ?? id} up`} disabled={i === 0 || save.isPending} onClick={() => save.mutate(moveInOrder(order, id, -1))}>
                <ArrowUp aria-hidden="true" />
              </button>
              <button type="button" className="icon-btn" aria-label={`Move ${names[id] ?? id} down`} disabled={i === order.length - 1 || save.isPending} onClick={() => save.mutate(moveInOrder(order, id, 1))}>
                <ArrowDown aria-hidden="true" />
              </button>
            </span>
          </li>
        ))}
      </ol>
      {save.isError && (
        <p className="notice bad" role="alert">
          {errorText(save.error, "The order could not be saved; try again")}
        </p>
      )}
    </div>
  );
}
