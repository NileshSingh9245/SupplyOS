import { queryOptions } from "@tanstack/react-query";
import { api } from "./api";

export interface ProductSummary {
  id: string;
  sku: string;
  name: string;
  unit: string;
  base_price: string;
}

export const productsQuery = queryOptions({
  queryKey: ["products-min"],
  queryFn: async ({ signal }) => {
    const { data } = await api.get<{ items: ProductSummary[] }>(
      "/products?page_size=200", { signal },
    );
    return data.items;
  },
});
