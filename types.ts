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
}