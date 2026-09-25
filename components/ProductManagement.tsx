import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, Pencil, UserCheck, UserX, ChevronLeft, ChevronRight, X, Loader2,
  AlertTriangle, Package, FileText, IndianRupee, Ruler, Eye, Truck,
} from 'lucide-react';
import Input from './Input';
import Select from './Select';
import SupplierSelector from '../shared/SupplierSelector';
import { Supplier } from '../api/suppliers';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import ExportButton from '../shared/ExportButton';
import { useNavigation } from '../context/NavigationContext';
import { ApiError, ConcurrencyConflictError } from '../api/client';
import {
  Product,
  ProductDetail,
  ProductFormPayload,
  listProducts,
  getProduct,
  createProduct,
  updateProduct,
  activateProduct,
  deactivateProduct,
  createUnitConversion,
} from '../api/products';
import { UnitOfMeasure, listUnits, createUnit } from '../api/units';
import MobileAccordionCard from '../shared/MobileAccordionCard';
import MobileFilterToggle from '../shared/MobileFilterToggle';

// Standard GST slabs — deliberately a closed, static set (not free-text),
// since GST rates are a fixed, government-defined list, not an open field.
const GST_RATE_OPTIONS = ['0', '3', '5', '12', '18', '28'];
// Display form for the shared Select component (which renders option labels
// verbatim) — this is also what's stored transiently in the `%`-suffixed
// UI state; stripped back to a plain number before it ever reaches the API.
const GST_RATE_DISPLAY_OPTIONS = GST_RATE_OPTIONS.map((rate) => `${rate}%`);

// Restricts a price field's typed input to digits and at most one decimal
// point — no minus sign, no "e" exponent notation, no letters. Used instead
// of <input type="number"> (whose native up/down spinner arrows were the
// actual reported complaint, and which still lets "e"/"+"/"-" through on
// most browsers despite looking numeric-only).
function sanitizeDecimalInput(raw: string): string {
  let value = raw.replace(/[^0-9.]/g, '');
  const firstDot = value.indexOf('.');
  if (firstDot !== -1) {
    value = value.slice(0, firstDot + 1) + value.slice(firstDot + 1).replace(/\./g, '');
  }
  return value;
}

const STATUS_BADGE: Record<string, string> = {
  ACTIVE: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  INACTIVE: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const ProductManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  // FR-PROD-04: Salesperson gets products.view ONLY — no create/edit/deactivate.
  const canCreate = hasPermission('products.create');
  const canEdit = hasPermission('products.update');
  const canActivate = hasPermission('products.activate');
  const canDeactivate = hasPermission('products.deactivate');

  const [products, setProducts] = useState<Product[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [showMobileFilters, setShowMobileFilters] = useState(false);

  const [showAddModal, setShowAddModal] = useState(false);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [viewingProduct, setViewingProduct] = useState<Product | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ product: Product; type: 'activate' | 'deactivate' } | null>(null);

  const fetchProducts = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listProducts({
        page,
        page_size: 10,
        search: search || undefined,
        status: statusFilter || undefined,
      });
      setProducts(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load products.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, statusFilter, showToast]);

  useEffect(() => {
    fetchProducts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, statusFilter]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setPage(1);
      fetchProducts();
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const handleConfirmStatusChange = async () => {
    if (!confirmAction) return;
    const { product, type } = confirmAction;
    try {
      if (type === 'activate') {
        await activateProduct(product.id, product.row_version);
      } else {
        await deactivateProduct(product.id, product.row_version);
      }
      showToast(`Product ${type === 'activate' ? 'activated' : 'deactivated'} successfully.`, 'success');
      setConfirmAction(null);
      fetchProducts();
    } catch (err) {
      if (err instanceof ConcurrencyConflictError) {
        showToast('This product was updated by someone else. Refresh and try again.', 'error');
      } else {
        showToast(err instanceof ApiError ? err.message : 'Something went wrong.', 'error');
      }
      setConfirmAction(null);
    }
  };

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <div className="flex items-center justify-between gap-3 md:block">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">
            Products
          </h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text"
              placeholder="Search name, SKU, HSN…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-colors text-[14px]"
            />
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
          >
            <option value="">All Statuses</option>
            <option value="ACTIVE">Active</option>
            <option value="INACTIVE">Inactive</option>
          </select>

          <ExportButton
            resource="products"
            exportPermission="products.export"
            search={search || undefined}
            status={statusFilter || undefined}
            page={page}
            pageSize={10}
            totalItems={totalItems}
          />

          {canCreate && (
            <button
              onClick={() => setShowAddModal(true)}
              className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[14px] px-4 py-2 rounded-lg transition-colors flex items-center justify-center gap-2 whitespace-nowrap"
            >
              <Plus size={16} /> Add Product
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={28} className="animate-spin text-gray-400" />
        </div>
      ) : products.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No products found.</div>
      ) : (
        <>
          {/* Desktop / tablet table */}
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">SKU</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Name</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">HSN</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">GST%</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Unit</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Selling Price</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">MRP</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Status</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {products.map((product) => (
                    <tr key={product.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{product.sku}</td>
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap">
                        <button onClick={() => setViewingProduct(product)} className="hover:text-[#0066ff] hover:underline text-left">
                          {product.name}
                        </button>
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{product.hsn_code || '—'}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{product.gst_rate !== null ? `${product.gst_rate}%` : '—'}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{product.base_uom.code}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">₹{product.selling_price}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">₹{product.mrp}</td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[product.status]}`}>
                          {product.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <div className="flex items-center justify-center gap-2">
                          <button onClick={() => setViewingProduct(product)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
                            <Eye size={16} />
                          </button>
                          {canEdit && (
                            <button onClick={() => setEditingProduct(product)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="Edit">
                              <Pencil size={16} />
                            </button>
                          )}
                          {product.status === 'ACTIVE'
                            ? canDeactivate && (
                                <button onClick={() => setConfirmAction({ product, type: 'deactivate' })} className="p-1.5 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500" title="Deactivate">
                                  <UserX size={16} />
                                </button>
                              )
                            : canActivate && (
                                <button onClick={() => setConfirmAction({ product, type: 'activate' })} className="p-1.5 rounded hover:bg-green-50 dark:hover:bg-green-900/20 text-green-600" title="Activate">
                                  <UserCheck size={16} />
                                </button>
                              )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Mobile cards (accordion — collapsed to header until tapped) */}
          <div className="md:hidden space-y-3">
            {products.map((product) => (
              <MobileAccordionCard
                key={product.id}
                title={product.name}
                subtitle={`${product.sku} · ${product.base_uom.code}`}
                badge={
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[product.status]}`}>
                    {product.status}
                  </span>
                }
              >
                <p className="text-[13px] text-gray-600 dark:text-gray-300 mb-3">
                  Selling: <span className="font-medium">₹{product.selling_price}</span> · MRP: <span className="font-medium">₹{product.mrp}</span>
                </p>
                <div className="flex gap-2">
                  <button onClick={() => setViewingProduct(product)} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300">
                    <Eye size={14} /> View
                  </button>
                  {canEdit && (
                    <button onClick={() => setEditingProduct(product)} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300">
                      <Pencil size={14} /> Edit
                    </button>
                  )}
                  {product.status === 'ACTIVE'
                    ? canDeactivate && (
                        <button onClick={() => setConfirmAction({ product, type: 'deactivate' })} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-red-300 dark:border-red-800 text-red-600">
                          <UserX size={14} /> Deactivate
                        </button>
                      )
                    : canActivate && (
                        <button onClick={() => setConfirmAction({ product, type: 'activate' })} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-green-300 dark:border-green-800 text-green-600">
                          <UserCheck size={14} /> Activate
                        </button>
                      )}
                </div>
              </MobileAccordionCard>
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} product{totalItems === 1 ? '' : 's'}</p>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300">
                <ChevronLeft size={16} />
              </button>
              <span className="text-[13px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages}</span>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300">
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        </>
      )}

      {showAddModal && (
        <ProductFormModal
          mode="create"
          onClose={() => setShowAddModal(false)}
          onSaved={() => { setShowAddModal(false); fetchProducts(); }}
        />
      )}

      {editingProduct && (
        <ProductFormModal
          mode="edit"
          product={editingProduct}
          onClose={() => setEditingProduct(null)}
          onSaved={() => { setEditingProduct(null); fetchProducts(); }}
        />
      )}

      {viewingProduct && (
        <ProductDetailModal
          productSummary={viewingProduct}
          onClose={() => setViewingProduct(null)}
          onEdit={canEdit ? () => { setEditingProduct(viewingProduct); setViewingProduct(null); } : undefined}
        />
      )}

      {confirmAction && (
        <ConfirmDialog
          title={confirmAction.type === 'activate' ? 'Activate Product' : 'Deactivate Product'}
          message={
            confirmAction.type === 'activate'
              ? `Activate ${confirmAction.product.name}? It will become available for new transactions again.`
              : `Deactivate ${confirmAction.product.name}? It cannot be selected for new transactions; historical records are preserved.`
          }
          onCancel={() => setConfirmAction(null)}
          onConfirm={handleConfirmStatusChange}
        />
      )}
    </div>
  );
};

interface ProductFormModalProps {
  mode: 'create' | 'edit';
  product?: Product;
  onClose: () => void;
  onSaved: () => void;
}

const ProductFormModal: React.FC<ProductFormModalProps> = ({ mode, product, onClose, onSaved }) => {
  const { showToast } = useToast();
  const { navigate } = useNavigation();
  const [sku, setSku] = useState(product?.sku || '');
  const [name, setName] = useState(product?.name || '');
  const [hsnCode, setHsnCode] = useState(product?.hsn_code || '');
  const [gstRate, setGstRate] = useState(product?.gst_rate ? String(Number(product.gst_rate)) : '');
  const [units, setUnits] = useState<UnitOfMeasure[]>([]);
  const [baseUomCode, setBaseUomCode] = useState(product?.base_uom.code || '');
  const [supplier, setSupplier] = useState<Supplier | null>(
    product?.supplier
      ? ({ id: product.supplier.id, name: product.supplier.name, supplier_code: product.supplier.supplier_code, phone: product.supplier.phone } as Supplier)
      : null
  );
  const [costPrice, setCostPrice] = useState(product?.cost_price || '0');
  const [sellingPrice, setSellingPrice] = useState(product?.selling_price || '0');
  const [mrp, setMrp] = useState(product?.mrp || '0');
  const [showAddUnit, setShowAddUnit] = useState(false);

  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [conversionFrom, setConversionFrom] = useState('');
  const [conversionTo, setConversionTo] = useState('');
  const [conversionFactor, setConversionFactor] = useState('');
  const [isAddingConversion, setIsAddingConversion] = useState(false);

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const loadUnits = useCallback(async () => {
    try {
      const list = await listUnits();
      setUnits(list);
    } catch (err) {
      showToast('Failed to load units.', 'error');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadUnits();
    if (mode === 'edit' && product) {
      getProduct(product.id).then(setDetail).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    if (!name.trim()) next.name = 'Product name is required';
    if (!sku.trim()) next.sku = 'SKU is required';
    else if (!/^[A-Z0-9][A-Z0-9_-]{0,49}$/.test(sku.toUpperCase())) next.sku = 'SKU must be alphanumeric (hyphen/underscore allowed)';
    if (!baseUomCode) next.baseUom = 'Base unit is required';
    if (hsnCode && !/^([0-9]{4}|[0-9]{6}|[0-9]{8})$/.test(hsnCode)) next.hsnCode = 'HSN must be 4, 6 or 8 digits';
    if (!gstRate) next.gstRate = 'GST rate is required';
    else if (!GST_RATE_OPTIONS.includes(gstRate)) next.gstRate = 'Select a valid GST slab';
    if (isNaN(Number(costPrice)) || Number(costPrice) < 0) next.costPrice = 'Enter a valid non-negative price';
    if (isNaN(Number(sellingPrice)) || Number(sellingPrice) < 0) next.sellingPrice = 'Enter a valid non-negative price';
    if (isNaN(Number(mrp)) || Number(mrp) < 0) next.mrp = 'Enter a valid non-negative price';
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    const unit = units.find((u) => u.code === baseUomCode);
    if (!unit) {
      showToast('Select a valid unit.', 'error');
      return;
    }
    setIsSubmitting(true);
    const payload: ProductFormPayload = {
      sku: sku.toUpperCase(),
      name,
      hsn_code: hsnCode || null,
      gst_rate: gstRate,
      base_uom_id: unit.id,
      supplier_id: supplier ? supplier.id : null,
      cost_price: String(costPrice || '0'),
      selling_price: String(sellingPrice || '0'),
      mrp: String(mrp || '0'),
    };
    try {
      if (mode === 'create') {
        await createProduct(payload);
        showToast('Product created successfully.', 'success');
      } else if (product) {
        await updateProduct(product.id, { ...payload, expected_row_version: product.row_version });
        showToast('Product updated successfully.', 'success');
      }
      onSaved();
    } catch (err) {
      if (err instanceof ConcurrencyConflictError) {
        showToast('This product was updated by someone else. Refresh and try again.', 'error');
      } else if (err instanceof ApiError && err.code === 'PROD-002') {
        showToast('A product with this code already exists.', 'error');
      } else if (err instanceof ApiError && err.code === 'PROD-007') {
        showToast('Selected supplier is no longer valid. Please choose another.', 'error');
      } else {
        showToast(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.', 'error');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAddConversion = async () => {
    if (!product || !conversionFrom || !conversionTo || !conversionFactor) return;
    if (conversionFrom === conversionTo) {
      showToast('Source and target unit must be different.', 'error');
      return;
    }
    setIsAddingConversion(true);
    try {
      await createUnitConversion(product.id, {
        from_uom_id: conversionFrom,
        to_uom_id: conversionTo,
        conversion_factor: conversionFactor,
      });
      showToast('Unit conversion added.', 'success');
      setConversionFrom('');
      setConversionTo('');
      setConversionFactor('');
      const refreshed = await getProduct(product.id);
      setDetail(refreshed);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'PROD-005') {
        showToast('A conversion between these units already exists.', 'error');
      } else {
        showToast(err instanceof ApiError ? err.message : 'Enter a valid unit conversion.', 'error');
      }
    } finally {
      setIsAddingConversion(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">
            {mode === 'create' ? 'Add Product' : 'Edit Product'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={20} />
          </button>
        </div>
        <div className="p-6">
          {/* Basic Information */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 flex items-center gap-2">
            <Package size={14} /> Basic Information
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4">
            <Input label="Product Name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
            <Input
              label="SKU / Product Code"
              value={sku}
              disabled={mode === 'edit'}
              onChange={(e) => setSku(e.target.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''))}
              error={errors.sku}
            />
          </div>

          {/* GST / Tax Information */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 mt-2 flex items-center gap-2">
            <FileText size={14} /> GST / Tax Information
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
            <Input
              label="HSN Code (Optional)"
              value={hsnCode}
              maxLength={8}
              onChange={(e) => setHsnCode(e.target.value.replace(/\D/g, ''))}
              error={errors.hsnCode}
            />
            <Select
              label="GST Rate %"
              options={GST_RATE_DISPLAY_OPTIONS}
              value={gstRate ? `${gstRate}%` : ''}
              onChange={(v) => setGstRate(v.replace('%', ''))}
              error={errors.gstRate}
            />
          </div>

          {/* Unit Information */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 mt-2 flex items-center gap-2">
            <Ruler size={14} /> Unit Information
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 items-start">
            <Select label="Base Unit" options={units.map((u) => u.code)} value={baseUomCode} onChange={setBaseUomCode} error={errors.baseUom} />
            <button
              type="button"
              onClick={() => setShowAddUnit(true)}
              className="mt-2 text-[13px] text-[#0066ff] dark:text-blue-400 font-medium hover:underline flex items-center gap-1"
            >
              <Plus size={14} /> Add a new unit
            </button>
          </div>

          {/* Supplier */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 mt-2 flex items-center gap-2">
            <Truck size={14} /> Supplier (Optional)
          </h4>
          <SupplierSelector value={supplier} onChange={setSupplier} label="Preferred Supplier" />
          <button
            type="button"
            onClick={() => { onClose(); navigate('Suppliers'); }}
            className="-mt-4 mb-6 text-[13px] text-[#0066ff] dark:text-blue-400 font-medium hover:underline flex items-center gap-1"
          >
            <Plus size={14} /> Add New Supplier
          </button>

          {/* Pricing */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 mt-2 flex items-center gap-2">
            <IndianRupee size={14} /> Pricing
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-4">
            <Input label="Cost Price (₹)" type="text" inputMode="decimal" value={costPrice} onChange={(e) => setCostPrice(sanitizeDecimalInput(e.target.value))} error={errors.costPrice} />
            <Input
              label="Selling Price (₹, tax-exclusive)"
              type="text"
              inputMode="decimal"
              value={sellingPrice}
              onChange={(e) => setSellingPrice(sanitizeDecimalInput(e.target.value))}
              error={errors.sellingPrice}
            />
            <Input label="MRP (₹)" type="text" inputMode="decimal" value={mrp} onChange={(e) => setMrp(sanitizeDecimalInput(e.target.value))} error={errors.mrp} />
          </div>
          <p className="text-[12px] text-gray-400 dark:text-gray-500 -mt-8 mb-6">
            Selling Price is tax-exclusive; GST is applied on top at billing time.
          </p>

          {/* Unit Conversion — edit mode only, needs an existing product */}
          {mode === 'edit' && product && (
            <>
              <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 mt-2 flex items-center gap-2">
                <Ruler size={14} /> Unit Conversion
              </h4>
              {detail && detail.unit_conversions.length > 0 && (
                <ul className="mb-4 space-y-1">
                  {detail.unit_conversions.map((c) => (
                    <li key={c.id} className="text-[13px] text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900 rounded px-3 py-2">
                      1 {c.from_uom.code} = {c.conversion_factor} {c.to_uom.code}
                    </li>
                  ))}
                </ul>
              )}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-x-4 items-start">
                <Select label="From Unit" options={units.map((u) => u.code)} value={units.find((u) => u.id === conversionFrom)?.code || ''} onChange={(code) => setConversionFrom(units.find((u) => u.code === code)?.id || '')} />
                <Select label="To Unit" options={units.map((u) => u.code)} value={units.find((u) => u.id === conversionTo)?.code || ''} onChange={(code) => setConversionTo(units.find((u) => u.code === code)?.id || '')} />
                <Input label="Factor (e.g. 24)" type="number" min={0} step="0.000001" value={conversionFactor} onChange={(e) => setConversionFactor(e.target.value)} />
              </div>
              <button
                type="button"
                onClick={handleAddConversion}
                disabled={isAddingConversion || !conversionFrom || !conversionTo || !conversionFactor}
                className="mb-6 -mt-6 text-[13px] text-[#0066ff] dark:text-blue-400 font-medium hover:underline flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isAddingConversion ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Add Conversion
              </button>
            </>
          )}

          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] py-3 rounded-lg transition-colors disabled:opacity-70 flex items-center justify-center gap-2"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />}
            {mode === 'create' ? 'Create Product' : 'Save Changes'}
          </button>
        </div>
      </div>

      {showAddUnit && (
        <AddUnitModal
          onClose={() => setShowAddUnit(false)}
          onCreated={(unit) => {
            setUnits((prev) => [...prev, unit]);
            // Only auto-select as Base Unit when none is chosen yet — in
            // edit mode a unit is often added just to use in a conversion
            // below, and must not silently overwrite an already-set base
            // unit out from under the user.
            setBaseUomCode((prev) => prev || unit.code);
            setShowAddUnit(false);
          }}
        />
      )}
    </div>
  );
};

const AddUnitModal: React.FC<{ onClose: () => void; onCreated: (unit: UnitOfMeasure) => void }> = ({ onClose, onCreated }) => {
  const { showToast } = useToast();
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleCreate = async () => {
    if (!code.trim() || !name.trim()) {
      showToast('Enter both a unit code and name.', 'error');
      return;
    }
    setIsSubmitting(true);
    try {
      const unit = await createUnit({ code: code.trim().toUpperCase(), name: name.trim() });
      showToast('Unit created.', 'success');
      onCreated(unit);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'PROD-006') {
        showToast('A unit with this code already exists.', 'error');
      } else {
        showToast(err instanceof ApiError ? err.message : 'Failed to create unit.', 'error');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
        <h3 className="text-[16px] font-semibold text-gray-900 dark:text-white mb-4">Add Unit of Measure</h3>
        <Input label="Code (e.g. PCS, KG)" value={code} maxLength={20} onChange={(e) => setCode(e.target.value.toUpperCase())} />
        <Input label="Name (e.g. Pieces, Kilogram)" value={name} maxLength={50} onChange={(e) => setName(e.target.value)} />
        <div className="grid grid-cols-2 gap-3 mt-2">
          <button onClick={onClose} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">
            Cancel
          </button>
          <button onClick={handleCreate} disabled={isSubmitting} className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium disabled:opacity-70">
            {isSubmitting ? 'Adding…' : 'Add'}
          </button>
        </div>
      </div>
    </div>
  );
};

const ProductDetailModal: React.FC<{ productSummary: Product; onClose: () => void; onEdit?: () => void }> = ({ productSummary, onClose, onEdit }) => {
  const { showToast } = useToast();
  const [detail, setDetail] = useState<ProductDetail | null>(null);

  useEffect(() => {
    getProduct(productSummary.id)
      .then(setDetail)
      .catch(() => showToast('Failed to load product details.', 'error'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productSummary.id]);

  const product = detail || productSummary;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{product.name}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={20} />
          </button>
        </div>
        <div className="p-6 space-y-4 text-[14px]">
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[product.status]}`}>{product.status}</span>
            <span className="text-gray-500 dark:text-gray-400">{product.sku}</span>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
            <div><dt className="text-gray-400 text-[12px] uppercase">HSN</dt><dd className="text-gray-900 dark:text-white">{product.hsn_code || '—'}</dd></div>
            <div><dt className="text-gray-400 text-[12px] uppercase">GST Rate</dt><dd className="text-gray-900 dark:text-white">{product.gst_rate !== null ? `${product.gst_rate}%` : '—'}</dd></div>
            <div><dt className="text-gray-400 text-[12px] uppercase">Base Unit</dt><dd className="text-gray-900 dark:text-white">{product.base_uom.name} ({product.base_uom.code})</dd></div>
            <div><dt className="text-gray-400 text-[12px] uppercase">Supplier</dt><dd className="text-gray-900 dark:text-white">{product.supplier ? `${product.supplier.name} (${product.supplier.phone || 'no phone'})` : '—'}</dd></div>
            <div><dt className="text-gray-400 text-[12px] uppercase">Stock (cache)</dt><dd className="text-gray-900 dark:text-white">{product.stock_qty_cache} <span className="text-gray-400 text-[11px]">(Inventory module pending)</span></dd></div>
            <div><dt className="text-gray-400 text-[12px] uppercase">Cost Price</dt><dd className="text-gray-900 dark:text-white">₹{product.cost_price}</dd></div>
            <div><dt className="text-gray-400 text-[12px] uppercase">Selling Price</dt><dd className="text-gray-900 dark:text-white">₹{product.selling_price} <span className="text-gray-400 text-[11px]">(excl. GST)</span></dd></div>
            <div><dt className="text-gray-400 text-[12px] uppercase">MRP</dt><dd className="text-gray-900 dark:text-white">₹{product.mrp}</dd></div>
          </dl>
          {detail && detail.unit_conversions.length > 0 && (
            <div>
              <dt className="text-gray-400 text-[12px] uppercase mb-2">Unit Conversions</dt>
              <ul className="space-y-1">
                {detail.unit_conversions.map((c) => (
                  <li key={c.id} className="text-[13px] text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900 rounded px-3 py-2">
                    1 {c.from_uom.code} = {c.conversion_factor} {c.to_uom.code}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {onEdit && (
            <button onClick={onEdit} className="w-full mt-2 flex items-center justify-center gap-2 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium hover:bg-gray-50 dark:hover:bg-gray-700">
              <Pencil size={14} /> Edit Product
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

const ConfirmDialog: React.FC<{ title: string; message: string; onCancel: () => void; onConfirm: () => void }> = ({
  title,
  message,
  onCancel,
  onConfirm,
}) => (
  <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
      <div className="flex items-center gap-3 mb-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30 shrink-0">
          <AlertTriangle size={20} className="text-amber-600 dark:text-amber-400" />
        </div>
        <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">{title}</h3>
      </div>
      <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">{message}</p>
      <div className="grid grid-cols-2 gap-3">
        <button onClick={onCancel} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">
          Cancel
        </button>
        <button onClick={onConfirm} className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium">
          Confirm
        </button>
      </div>
    </div>
  </div>
);

export default ProductManagement;
