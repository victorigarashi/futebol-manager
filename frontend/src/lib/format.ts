const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
export const formatMoney = (cents: number) => currency.format(cents / 100);
export const positionName: Record<string, string> = { GK: "Goleiro", DF: "Defesa", MF: "Meio-campo", ST: "Ataque" };
