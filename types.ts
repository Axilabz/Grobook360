import React from 'react';

export enum AuthView {
  SIGN_IN = 'SIGN_IN',
  SIGN_UP = 'SIGN_UP',
  FORGOT_PASSWORD = 'FORGOT_PASSWORD',
  RESET_PASSWORD = 'RESET_PASSWORD',
}

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: React.ReactNode;
  icon?: React.ReactNode;
  onIconClick?: () => void;
  infoContent?: React.ReactNode;
  forceShowTooltip?: boolean;
  labelClassName?: string;
}

export interface SelectProps {
  label: string;
  options: string[];
  error?: React.ReactNode;
  value?: string;
  onChange: (value: string) => void;
  className?: string;
  placeholder?: string;
  disabled?: boolean;
  labelClassName?: string;
  /** Show the "Add new item..." creatable-entry row at the bottom of the dropdown. Defaults to true (existing behavior everywhere) — set false for fixed-enum fields (e.g. a period/comparison picker) where an ad-hoc value would never be valid. */
  allowAddNew?: boolean;
}