import Storefront from "@/components/Storefront";

export default async function ProductPage({ params }) {
  const { productId } = await params;
  return <Storefront initialProductId={productId} />;
}
